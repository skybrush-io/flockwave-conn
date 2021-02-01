"""Generic networking-related utility functions."""

from ipaddress import ip_address, ip_network, IPv6Address, IPv6Network
from netifaces import AF_INET, AF_INET6, AF_LINK, gateways, ifaddresses, interfaces
from typing import Dict, Optional, Sequence, Tuple, Union

import platform
import trio.socket

__all__ = (
    "canonicalize_mac_address",
    "create_socket",
    "enable_tcp_keepalive",
    "find_interfaces_with_address",
    "find_interfaces_in_network",
    "format_socket_address",
    "get_address_of_network_interface",
    "get_all_ipv4_addresses",
    "get_link_layer_address_mapping",
    "get_socket_address",
    "is_mac_address_unicast",
    "is_mac_address_universal",
    "resolve_network_interface_or_address",
)


def canonicalize_mac_address(address: str) -> str:
    """Returns a canonical representation of a MAC address, with all whitespace
    stripped, hexadecimal characters converted to lowercase and dashes replaced
    with colons.
    """
    return address.strip().lower().replace("-", ":")


def create_socket(socket_type) -> trio.socket.socket:
    """Creates an asynchronous socket with the given type.

    Asynchronous sockets have asynchronous sender and receiver methods so
    you need to use the `await` keyword with them.

    Parameters:
        socket_type: the type of the socket (``socket.SOCK_STREAM`` for
            TCP sockets, ``socket.SOCK_DGRAM`` for UDP sockets)

    Returns:
        the newly created socket
    """
    sock = trio.socket.socket(trio.socket.AF_INET, socket_type)
    if hasattr(trio.socket, "SO_REUSEADDR"):
        # SO_REUSEADDR does not exist on Windows, but we don't really need
        # it on Windows either
        sock.setsockopt(trio.socket.SOL_SOCKET, trio.socket.SO_REUSEADDR, 1)
    if hasattr(trio.socket, "SO_REUSEPORT"):
        # Needed on Mac OS X to work around an issue with an earlier
        # instance of the flockctrl process somehow leaving a socket
        # bound to the UDP broadcast address even when the process
        # terminates
        sock.setsockopt(trio.socket.SOL_SOCKET, trio.socket.SO_REUSEPORT, 1)
    return sock


def enable_tcp_keepalive(
    sock, after_idle_sec: int = 1, interval_sec: int = 3, max_fails: int = 5
) -> None:
    """Enables TCP keepalive settings on the given socket.

    Parameters:
        after_idle_sec: number of seconds after which the socket should start
            sending TCP keepalive packets
        interval_sec: number of seconds between consecutive TCP keepalive
            packets
        max_fails: maximum number of failures allowed before terminating the
            TCP connection
    """
    sock.setsockopt(trio.socket.SOL_SOCKET, trio.socket.SO_KEEPALIVE, 1)

    if hasattr(trio.socket, "TCP_KEEPIDLE"):
        print("A")
        sock.setsockopt(
            trio.socket.IPPROTO_TCP, trio.socket.TCP_KEEPIDLE, after_idle_sec
        )
    elif platform.system() == "Darwin":
        # This is for macOS
        try:
            TCP_KEEPALIVE = 0x10  # scraped from the Darwin headers
            sock.setsockopt(trio.socket.IPPROTO_TCP, TCP_KEEPALIVE, after_idle_sec)
        except Exception as ex:
            print(repr(ex))
            pass

    if hasattr(trio.socket, "TCP_KEEPINTVL"):
        sock.setsockopt(
            trio.socket.IPPROTO_TCP, trio.socket.TCP_KEEPINTVL, interval_sec
        )

    if hasattr(trio.socket, "TCP_KEEPCNT"):
        sock.setsockopt(trio.socket.IPPROTO_TCP, trio.socket.TCP_KEEPCNT, max_fails)


def find_interfaces_with_address(address: str) -> Sequence[Tuple[str, str]]:
    """Finds the network interfaces of the current machine that contain the given
    address in their network.

    Parameters:
        address: the address that we are looking for

    Returns:
        for all the network interfaces that have at least one address that
        belongs to the given network, the name of the network interface itself and
        the network of the interface, in a tuple
    """
    address = ip_address(address)
    if isinstance(address, IPv6Address):
        family = AF_INET6
    else:
        family = AF_INET

    candidates = []
    for interface in interfaces():
        specs = ifaddresses(interface).get(family) or []
        ip_addresses_in_network = (
            (spec.get("addr"), spec.get("netmask")) for spec in specs
        )
        for if_address, netmask in ip_addresses_in_network:
            network = ip_network(f"{if_address}/{netmask}", strict=False)
            if address in network:
                candidates.append((interface, network))

    return candidates


def find_interfaces_in_network(network: str) -> Sequence[Tuple[str, str, str]]:
    """Finds the network interfaces of the current machine that have at
    least one address that belongs to the given network.

    Parameters:
        network: the network that we are looking for

    Returns:
        for all the network interfaces that have at least one address that
        belongs to the given network, the name of the network interface
        itself, the matched address and the network of the interface, in
        a tuple
    """
    network = ip_network(network)
    if isinstance(network, IPv6Network):
        family = AF_INET6
    else:
        family = AF_INET

    candidates = []
    for interface in interfaces():
        specs = ifaddresses(interface).get(family) or []
        ip_addresses_in_network = (
            (spec.get("addr"), spec.get("netmask"))
            for spec in specs
            if ip_address(str(spec.get("addr"))) in network
        )
        for address, netmask in ip_addresses_in_network:
            candidates.append(
                (
                    interface,
                    address,
                    str(ip_network(f"{address}/{netmask}", strict=False))
                    if netmask
                    else None,
                )
            )

    return candidates


def format_socket_address(
    sock, format: str = "{host}:{port}", in_subnet_of: Optional[Union[str, int]] = None
) -> str:
    """Formats the address that the given socket is bound to in the
    standard hostname-port format.

    Parameters:
        sock: the socket to format
        format: format string in brace-style that is used by
            ``str.format()``. The tokens ``{host}`` and ``{port}`` will be
            replaced by the hostname and port.
        in_subnet_of: the IP address and port that should preferably be in the
            same subnet as the response. This is used only if the socket is
            bound to all interfaces, in which case we will try to pick an
            interface that is in the same subnet as the remote address.

    Returns:
        str: a formatted representation of the address and port of the
            socket
    """
    host, port = get_socket_address(sock, in_subnet_of)
    return format.format(host=host, port=port)


def get_address_of_network_interface(value: str, family: int = AF_INET) -> str:
    """Returns the address of the given network interface in the given
    address family.

    If the interface has multiple addresses, this function returns the first
    one only.

    Parameters:
        value: the name of the network interface
        family: the address family of the interface; one of the `AF_` constants
            from the `netifaces` module. Use `AF_INET` for the standard IPv4
            address and `AF_LINK` for the MAC address.

    Returns:
        the address of the given network interface

    Raises:
        ValueError: if the given network interface has no address in the given
            address family
    """
    addresses = ifaddresses(value).get(family)
    if addresses:
        return addresses[0]["addr"]
    else:
        raise ValueError(f"interface {value} has no address")


def get_all_ipv4_addresses() -> Sequence[str]:
    """Returns all IPv4 addresses of the current machine."""
    result = []
    for iface in interfaces():
        addresses = ifaddresses(iface)
        if AF_INET in addresses:
            result.append(addresses[AF_INET][0]["addr"])
    return result


def get_broadcast_address_of_network_interface(
    value: str, family: int = AF_INET
) -> str:
    """Returns the broadcast address of the given network interface in the given
    address family.

    Parameters:
        value: the name of the network interface
        family: the address family of the interface; one of the `AF_` constants
            from the `netifaces` module

    Returns:
        the broadcast address of the given network interface

    Raises:
        ValueError: if the given network interface has no broadcast address in
            the given address family
    """
    addresses = ifaddresses(value).get(family)
    if addresses:
        return addresses[0]["broadcast"]
    else:
        raise ValueError(f"interface {value} has no broadcast address")


def get_link_layer_address_mapping() -> Dict[str, str]:
    """Returns a dictionary mapping interface names to their corresponding
    link-layer (MAC) addresses.

    We assume that one interface may have only one link-layer address.
    """
    result = {}
    for iface in interfaces():
        addresses = ifaddresses(iface)
        if AF_LINK in addresses:
            result[iface] = canonicalize_mac_address(addresses[AF_LINK][0]["addr"])
    return result


def get_socket_address(
    sock, in_subnet_of: Optional[Tuple[str, int]] = None
) -> Tuple[str, int]:
    """Gets the hostname and port that the given socket is bound to.

    Parameters:
        sock: the socket for which we need its address
        in_subnet_of: the IP address and port that should preferably be in the
            same subnet as the response. This is used only if the socket is
            bound to all interfaces, in which case we will try to pick an
            interface that is in the same subnet as the remote address.

    Returns:
        the host and port where the socket is bound to
    """
    if hasattr(sock, "getsockname"):
        host, port = sock.getsockname()
    else:
        host, port = sock

    # Canonicalize the value of 'host'
    if host == "0.0.0.0":
        host = ""

    # If host is empty and an address is given, try to find one from
    # our IP addresses that is in the same subnet as the given address
    if not host and in_subnet_of:
        remote_host, _ = in_subnet_of
        try:
            remote_host = ip_address(remote_host)
        except Exception:
            remote_host = None

        if remote_host:
            for interface in interfaces():
                # We are currently interested only in IPv4 addresses
                specs = ifaddresses(interface).get(AF_INET)
                if not specs:
                    continue
                for spec in specs:
                    if "addr" in spec and "netmask" in spec:
                        net = ip_network(
                            spec["addr"] + "/" + spec["netmask"], strict=False
                        )
                        if remote_host in net:
                            host = spec["addr"]
                            break

        if not host:
            # Try to find the default gateway and then use the IP address of
            # the network interface corresponding to the gateway. This may
            # or may not work; most likely it won't, but that's the best we
            # can do.
            gateway = gateways()["default"][AF_INET]
            if gateway:
                _, interface = gateway
                specs = ifaddresses(interface).get(AF_INET)
                for spec in specs:
                    if "addr" in spec:
                        host = spec["addr"]
                        break

    return host, port


def _get_first_byte_of_mac_address(address: str) -> int:
    """Returns the first byte of a MAC address (specified as colon- or
    dash-separated hex digits).
    """
    for index, ch in enumerate(address):
        if ch in ("-:"):
            try:
                return int(address[:index], 16)
            except ValueError:
                raise ValueError("input is not a valid MAC address") from None

    raise ValueError("input is not a valid MAC address")


def is_mac_address_unicast(address: str) -> bool:
    """Returns whether a given MAC address (specified as colon- or dash-separated
    hex digits) is a unicast MAC address.
    """
    return not bool(_get_first_byte_of_mac_address(address) & 0x01)


def is_mac_address_universal(address: str) -> bool:
    """Returns whether a given MAC address (specified as colon-separated
    hex digits) is a universal, vendor-assigned MAC address.
    """
    return not bool(_get_first_byte_of_mac_address(address) & 0x03)


def resolve_network_interface_or_address(value: Optional[str]) -> str:
    """Takes the name of a network interface or an IP address as input,
    and returns the resolved and validated IP address.

    This process might call `netifaces.ifaddresses()` et al in the
    background, which could potentially be blocking. It is advised to run
    this function in a separate worker thread.

    Parameters:
        value: the IP address to validate, or the interface whose IP address
            we are about to retrieve.

    Returns:
        the IPv4 address of the interface.
    """
    try:
        return str(ip_address(value))
    except ValueError:
        return str(get_address_of_network_interface(value))
