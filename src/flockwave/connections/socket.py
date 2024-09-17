"""Connections via TCP or UDP sockets."""

import struct

from abc import abstractmethod
from dataclasses import dataclass
from errno import EADDRNOTAVAIL
from ipaddress import ip_address, ip_network, IPv4Network, IPv6Network
from trio import open_tcp_stream, to_thread, SocketStream
from trio.socket import (
    inet_aton,
    socket,
    IPPROTO_IP,
    IP_ADD_MEMBERSHIP,
    IP_MULTICAST_IF,
    IP_MULTICAST_TTL,
    SOCK_DGRAM,
    SOCK_STREAM,
    SOL_SOCKET,
    SO_BROADCAST,
    SocketType,
)
from typing import Literal, cast, Optional, Union

from flockwave.networking import (
    create_socket,
    find_interfaces_in_network,
    get_address_of_network_interface,
    get_broadcast_address_of_network_interface,
    resolve_network_interface_or_address,
)

from .base import (
    BroadcastAddressOverride,
    BroadcastConnection,
    ConnectionBase,
    ListenerConnection,
    RWConnection,
)
from .capabilities import Capabilities, CapabilitySupport
from .errors import ConnectionError, NoBroadcastAddressError
from .factory import create_connection
from .stream import StreamConnectionBase
from .types import IPAddressAndPort

__all__ = (
    "BroadcastUDPListenerConnection",
    "MulticastUDPListenerConnection",
    "TCPListenerConnection",
    "TCPStreamConnection",
    "UDPListenerConnection",
    "UDPSocketConnection",
    "UnixDomainSocketConnection",
)


class InternetAddressMixin:
    """Mixin class that adds an "address" property to a connection, consisting
    of an IP address and a port.
    """

    _address: Optional[IPAddressAndPort]

    def __init__(self):
        self._address = None

    @property
    def address(self) -> Optional[IPAddressAndPort]:
        """Returns the IP address and port of the socket, in the form of a
        tuple.
        """
        return self._address

    @property
    def ip(self) -> str:
        """Returns the IP address that the socket is bound to.

        Raises:
            RuntimeError: if the socket is not bound to an IP address
        """
        if self.address:
            return self.address[0]
        else:
            raise RuntimeError("socket is not bound to an IP address")

    @property
    def port(self) -> int:
        """Returns the port that the socket is bound to.

        Raises:
            RuntimeError: if the socket is not bound to an IP address
        """
        if self.address:
            return self.address[1]
        else:
            raise RuntimeError("socket is not bound to an IP address")


@dataclass
class SocketBinding:
    """Object that describes how to determine the address to bind a socket to.

    Socket connections support the following types of bindings:

      - Fixed hostname or IP address. Always binds the socket to the same
        hostname or IP address.

      - Interface-based binding. Finds a network interface with a given name and
        binds the socket to the IP address of the interface if it has one.

      - Subnet-based binding. Finds a network interface that has an address in
        a given IP subnet and binds the socket to the address of that network
        interface.

    For interface and subnet-based binding, the binding object can be instructed
    to bind to the _broadcast_ address instead of the address of the network
    interface itself. Use the `bind_to_broadcast()` setter to achieve this.
    """

    mode: Literal["fixed", "interface", "subnet"] = "fixed"
    """The type of the socket binding."""

    value: str = ""
    """The IP address to bind to in case of a fixed binding, or the name of the
    interface in interface-based binding, or the subnet specification in case
    of a subnet-based binding.
    """

    port: int = 0
    """The port to bind to."""

    _bind_to_broadcast: bool = False
    """Whether to bind to the broadcast address of the interface instead of
    to its own address. Ignored for fixed bindings.
    """

    @classmethod
    def fixed(cls, host: str, port: int = 0):
        return cls("fixed", host, port)

    @classmethod
    def to_interface(cls, interface: str, port: int = 0):
        return cls("interface", interface, port)

    @classmethod
    def to_subnet(cls, subnet: Union[IPv4Network, IPv6Network, str], port: int = 0):
        return cls("subnet", str(subnet), port)

    @property
    def fixed_address(self) -> Optional[IPAddressAndPort]:
        """Returns the IP address and port to bind to if the binding is fixed,
        otherwise returns ``None``.
        """
        return (self.value, self.port) if self.mode == "fixed" else None

    def bind_to_broadcast(self, value: bool = True) -> None:
        """Instructs the binding object to bind to the broadcast address of the
        interface in subnet-bound or interface-bound modes.
        """
        self._bind_to_broadcast = bool(value)

    async def get_broadcast_address(self) -> str:
        """Returns the IP address to send broadcast messages to.

        In fixed mode, broadcast messages are sent to 255.255.255.255 as we do
        not know which subnet to narrow it down to.

        In interface-bound mode, broadcast messages are sent to the broadcast
        address of the interface.

        In subnet-bound mode, broadcast messages are sent to the broadcast
        address of the subnet.
        """
        if self.mode == "fixed":
            return "255.255.255.255"
        elif self.mode == "interface":
            return await to_thread.run_sync(
                get_broadcast_address_of_network_interface, self.value
            )
        elif self.mode == "subnet":
            network = ip_network(self.value)
            return str(network.broadcast_address)
        else:
            raise ValueError("Unknown socket binding mode: {self.mode!r}")

    async def resolve(self) -> IPAddressAndPort:
        """Resolves the IP address and port to bind to.

        Returns:
            the IP address and port to bind the socket to

        Raises:
            ConnectionError: if a non-fixed binding mode is specified and it is
                not possible to find a network interface satisfying the binding
                conditions.
        """
        address = await self._resolve_address()
        return address, self.port

    async def _resolve_address(self) -> str:
        """Resolves the IP address to bind to.

        Returns:
            the IP address to bind the socket to

        Raises:
            ConnectionError: if a non-fixed binding mode is specified and it is
                not possible to find a network interface satisfying the binding
                conditions.
        """
        if self.mode == "fixed":
            return self.value
        elif self.mode == "interface":
            try:
                return await to_thread.run_sync(
                    get_broadcast_address_of_network_interface
                    if self._bind_to_broadcast
                    else get_address_of_network_interface,
                    self.value,
                    abandon_on_cancel=True,
                )
            except ValueError:
                raise ConnectionError(
                    f"Network interface {self.value!r} has no IP address"
                ) from None
        elif self.mode == "subnet":
            candidates = await to_thread.run_sync(
                find_interfaces_in_network, self.value, abandon_on_cancel=True
            )
            if candidates:
                interface, address, network = candidates[0]
                if self._bind_to_broadcast:
                    network = ip_network(network) if network else None
                    if network is None:
                        address = await to_thread.run_sync(
                            get_broadcast_address_of_network_interface,
                            interface,
                            abandon_on_cancel=True,
                        )
                    else:
                        address = str(network.broadcast_address)
                return address
            else:
                raise ConnectionError(
                    f"No network interface corresponds to subnet {self.value!r}"
                )
        else:
            raise ValueError("Unknown socket binding mode: {self.mode!r}")


class SocketConnectionBase(ConnectionBase, InternetAddressMixin):
    """Base class for connection objects using TCP or UDP sockets."""

    _socket: Optional[SocketType]

    def __init__(self):
        ConnectionBase.__init__(self)
        InternetAddressMixin.__init__(self)
        self._socket = None

    @InternetAddressMixin.address.getter
    def address(self) -> Optional[IPAddressAndPort]:
        """Returns the IP address and port of the socket, in the form of a
        tuple.
        """
        # The policy in this getter is that we return the address of the
        # socket itself if it is not None, irrespectively of what was set
        # before. We reach out to the private _address property only if the
        # socket is not bound
        if self._socket is None:
            # No socket yet; try to obtain the address from the "_address"
            # property instead
            if self._address is None:
                raise ValueError("socket is not open yet")
            else:
                return super().address
        else:
            # Ask the socket for its address
            return self._socket.getsockname()

    @property
    def socket(self):
        """Returns the socket object itself."""
        return self._socket

    async def _close(self):
        """Closes the socket connection."""
        assert self._socket is not None
        self._socket.close()
        self._socket = None

    @abstractmethod
    async def _create_and_open_socket(self) -> SocketType:
        """Creates and opens the socket that the connection will use."""
        raise NotImplementedError

    async def _open(self):
        """Opens the socket connection."""
        self._socket = await self._create_and_open_socket()


@create_connection.register("tcp")
class TCPStreamConnection(StreamConnectionBase, InternetAddressMixin):
    """Connection object that wraps a Trio TCP stream."""

    def __init__(self, host: str, port: int, **kwds):
        """Constructor.

        Parameters:
            host: the IP address or hostname that the socket will connect to.
            port: the port number that the socket will connect to.
        """
        StreamConnectionBase.__init__(self)
        InternetAddressMixin.__init__(self)
        self._address: IPAddressAndPort = (host or "", port or 0)

    async def _create_stream(self) -> SocketStream:
        """Creates a new non-blocking reusable TCP socket and connects it to
        the target of the connection.
        """
        host, port = self._address
        return await open_tcp_stream(host, port)


class IncomingTCPStreamConnection(StreamConnectionBase, InternetAddressMixin):
    """Connection object that is created when the socket behind a listening
    TCPListenerConnection_ accepts a new client connection.
    """

    def __init__(self, address: IPAddressAndPort, socket: SocketType):
        """Constructor.

        Parameters:
            socket: the Trio socket that leads to the connected client
        """
        StreamConnectionBase.__init__(self)
        InternetAddressMixin.__init__(self)
        self._address = address
        self._stored_socket = socket

    async def _create_stream(self) -> SocketStream:
        """Creates a Trio SocketStream anew non-blocking reusable TCP socket and connects it to
        the target of the connection.
        """
        if self._stored_socket is not None:
            stream = SocketStream(self._stored_socket)
            self._stored_socket = None
            return stream
        else:
            raise RuntimeError("this connection can be opened only once")


@create_connection.register("tcp-listen")
class TCPListenerConnection(
    SocketConnectionBase, ListenerConnection[IncomingTCPStreamConnection]
):
    """Connection object that wraps a Trio TCP listener that listens for
    incoming TCP connections on a specific port.
    """

    _backlog: int
    _binding: SocketBinding

    def __init__(self, host: str = "", port: int = 0, *, backlog: int = -1, **kwds):
        """Constructor.

        Parameters:
            host: the IP address or hostname that the socket will listen on.
            port: the port number that the socket will listen on; zero means to
                pick an unused port
            backlog: the size of the backlog for incoming connections; negative
                numbers mean that the OS should choose a reasonable default
        """
        SocketConnectionBase.__init__(self)
        ListenerConnection.__init__(self)

        self._backlog = backlog
        self._binding = SocketBinding.fixed(host or "", port or 0)

        # Maintain compatibility with InternetAddressMixin
        self._address = self._binding.fixed_address

    async def _create_and_open_socket(self) -> SocketType:
        """Creates and opens the socket that the connection will use."""
        sock = create_socket(SOCK_STREAM)
        await self._bind_socket(sock)
        if self._backlog >= 0:
            sock.listen(self._backlog)
        else:
            sock.listen()
        return cast(SocketType, sock)

    async def _bind_socket(self, sock: SocketType) -> None:
        """Binds the given TCP socket to the address where it should listen for
        incoming TCP connections.
        """
        address = await self._binding.resolve()
        await sock.bind(address)

    async def accept(self) -> IncomingTCPStreamConnection:
        assert self._socket is not None
        client_socket, address = await self._socket.accept()
        connection = IncomingTCPStreamConnection(address, client_socket)
        await connection.open()
        return connection


@create_connection.register("udp")
class UDPSocketConnection(SocketConnectionBase, RWConnection[bytes, bytes]):
    """Connection object that uses a UDP socket that listens on an arbitrary
    IP address and port and is connected to a specific target IP address and port.
    """

    _address: IPAddressAndPort

    def __init__(
        self,
        host: str,
        port: int,
        **kwds,
    ):
        """Constructor.

        Parameters:
            host: the IP address or hostname that the socket will connect to
            port: the port number that the socket will connect to
        """
        super().__init__()
        self._address = host, port

    async def _create_and_open_socket(self):
        """Creates a new non-blocking reusable UDP socket that is not bound
        anywhere yet.
        """
        sock = create_socket(SOCK_DGRAM)
        await self._connect_socket(sock)
        return sock

    async def _connect_socket(self, sock) -> None:
        """Binds the given UDP socket to the address where it should send the
        packets to.
        """
        await sock.connect(self._address)

    async def read(self, size: int = 4096, flags: int = 0) -> bytes:
        """Reads an incoming UDP packet from the connection.

        Parameters:
            size: the maximum number of bytes to return
            flags: flags to pass to the underlying ``recvfrom()`` call;
                see the UNIX manual for details

        Returns:
            (bytes, tuple): the received data and the address it was
                received from, or ``(b"", None)`` if there was nothing to
                read.
        """
        if self._socket is not None:
            data = await self._socket.recv(size, flags)
            if not data:
                # Remote side closed connection
                await self.close()
            return data
        else:
            return b""

    async def write(self, data: bytes, flags: int = 0) -> None:
        """Writes the given data to the socket connection.

        Parameters:
            data: the bytes to write
            flags: additional flags to pass to the underlying ``send()``
                call; see the UNIX manual for details.
        """
        if self._socket is not None:
            await self._socket.send(data, flags)
        else:
            raise RuntimeError("connection does not have a socket")


@create_connection.register("udp-listen")
class UDPListenerConnection(
    SocketConnectionBase,
    RWConnection[tuple[bytes, IPAddressAndPort], tuple[bytes, IPAddressAndPort]],
    BroadcastConnection[Union[bytes, tuple[bytes, IPAddressAndPort]]],
    BroadcastAddressOverride[IPAddressAndPort],
    CapabilitySupport,
):
    """Connection object that uses a UDP socket that listens on a specific
    IP address and port.

    The socket can also be used for sending data to arbitrary IP addresses and
    ports. However, this means that the objects being sent on this socket are
    actually tuples containing the raw data _and_ the address to send the data
    to.
    """

    _allow_broadcast: bool
    """Whether broadcasts are allowed on this connection. Specified at
    construction time.
    """

    _binding: SocketBinding
    """Binding object that decides the IP address to bind to when the connection
    is opened.
    """

    _broadcast_interface: Optional[str] = None
    """Interface to send broadcast packets to, as specified by the user at
    construction time. ``None`` if the user has no preference.
    """

    _broadcast_port: Optional[int] = None
    """Port to send broadcast packets to."""

    _inferred_broadcast_address: Optional[IPAddressAndPort] = None
    """Inferred broadcast address when the socket is open and it is bound to a
    subnet or an interface; ``None`` if there is no inferred broadcast address.
    """

    _multicast_interface: Optional[str] = None
    """Interface to send multicast packets to, as specified by the user at
    construction time. ``None`` if the user has no preference.
    """

    _multicast_ttl: Optional[int] = None
    """Multicast packet time-to-live values, as specified by the user at
    construction time. ``None`` if the user has no preference.
    """

    _user_defined_broadcast_address: Optional[IPAddressAndPort] = None
    """User-defined broadcast address; ``None`` if the user did not specify a
    broadcast address explicitly.
    """

    def __init__(
        self,
        host: Optional[str] = "",
        port: int = 0,
        interface: Optional[str] = None,
        subnet: Optional[Union[IPv4Network, IPv6Network, str]] = None,
        allow_broadcast: bool = False,
        broadcast_interface: Optional[str] = None,
        broadcast_port: Optional[int] = None,
        multicast_interface: Optional[str] = None,
        multicast_ttl: Optional[int] = None,
        **kwds,
    ):
        """Constructor.

        Parameters:
            host: the IP address or hostname that the socket will bind to. The
                default value means that the socket will bind to all IP
                addresses of the local machine, unless a subnet or an interface
                is specified in `subnet` or `interface`.
            port: the port number that the socket will bind to. Zero means that
                the socket will choose a random ephemeral port number on its
                own.
            interface: the network interface to bind to. When specified, the
                socket will bind to the IP address of the network interface if
                it has one. ``None`` means not to bind to a specific interface.
                Takes precedence over `host` and `subnet`.
            subnet: the IP subnet to bind to. When specified, the socket will
                bind to the first network interface that has an IP address in
                the given subnet. ``None`` means not to bind to a specific
                subnet. Takes precedence over `host`, but is overridden by
                `interface`.
            allow_broadcast: whether to allow the socket to send broadcast
                packets. Note that if you want to receive broadcast packets as
                well as sending them, the host needs to be set to the empty
                string (representing "all interfaces") because broadcast packets
                arrive on a different address than unicast packets
            broadcast_interface: the name or IP address of the network interface
                on which broadcast packets should be sent from this socket.
                Applies only if ``allow_broadcast`` is truthy. ``None`` means
                to use the default setting of the OS.
            broadcast_port: the destination port to use when sending broadcasts.
                Automatically sets `allow_broadcast` to `True` when it is not
                `None`. `None` means that broadcasts should use the same port
                as the one the socket is bound to.
            multicast_interface: the name or IP address of the network interface
                on which multicast packets should be sent from this socket.
                ``None`` means not to configure the multicast interface for
                this socket.
            multicast_ttl: the TTL (time-to-live) value of multicast packets
                sent from this socket. ``None`` means not to configure the
                TTL value of outbound packets.
        """
        super().__init__()

        port = port or 0
        if interface is not None:
            # Bind to a specific network interface
            self._binding = SocketBinding.to_interface(interface, port)
        elif subnet is not None:
            # Bind to a specific subnet
            self._binding = SocketBinding.to_subnet(subnet, port)
        else:
            # Bind to a fixed IP address and port
            self._binding = SocketBinding.fixed(host or "", port)

        self._broadcast_interface = broadcast_interface
        self._broadcast_port = (
            int(broadcast_port) if broadcast_port is not None else None
        )

        self._multicast_interface = multicast_interface
        self._multicast_ttl = int(multicast_ttl) if multicast_ttl is not None else None

        if self._broadcast_port is not None:
            self._allow_broadcast = True
        else:
            self._allow_broadcast = bool(int(allow_broadcast))

        # Maintain compatibility with InternetAddressMixin
        self._address = self._binding.fixed_address

    async def _create_and_open_socket(self):
        """Creates a new non-blocking reusable UDP socket that is not bound
        anywhere yet.
        """
        sock = create_socket(SOCK_DGRAM)

        # Set the broadcast interface of the socket if the user specified one
        # explicitly
        if self._allow_broadcast:
            effective_broadcast_interface: Optional[str] = None

            sock.setsockopt(SOL_SOCKET, SO_BROADCAST, 1)
            if self._broadcast_interface is not None:
                # User specified a broadcast interface explicitly
                effective_broadcast_interface = await to_thread.run_sync(
                    resolve_network_interface_or_address, self._broadcast_interface
                )

            if effective_broadcast_interface is not None:
                try:
                    from socket import IP_BROADCAST_IF  # type: ignore
                except ImportError:
                    raise RuntimeError(
                        "this OS does not support setting the broadcast interface of a socket"
                    ) from None
                sock.setsockopt(
                    IPPROTO_IP,
                    IP_BROADCAST_IF,
                    inet_aton(effective_broadcast_interface),
                )

        # Set the multicast TTL value if the user specified one explicitly
        if self._multicast_ttl is not None:
            sock.setsockopt(IPPROTO_IP, IP_MULTICAST_TTL, self._multicast_ttl)

        # Set the multicast interface if the user specified one explicitly
        if self._multicast_interface is not None:
            multicast_interface = await to_thread.run_sync(
                resolve_network_interface_or_address, self._multicast_interface
            )
            sock.setsockopt(IPPROTO_IP, IP_MULTICAST_IF, inet_aton(multicast_interface))

        # Now we can bind the socket to its designated address
        await self._bind_socket(sock)

        # Assign the broadcast address to this socket if the user hasn't assigned
        # one yet
        if self._allow_broadcast:
            # If broadcast is allowed and no broadcast port is defined, use the
            # same port for broadcasting as the one used for unicasting, so we
            # need to get the port that the socket is bound to.
            #
            # Note that we need to do this here; by the time we get here, we
            # already have our definite port number even if originally it was
            # defined as zero (i.e. the OS should pick one)
            if self._broadcast_port is None:
                new_address = sock.getsockname()
                if isinstance(new_address, tuple) and len(new_address) > 1:
                    self._broadcast_port = new_address[1]

            # Derive the broadcast address and store it in _inferred_broadcast_address.
            # This can be overridden explicitly by the user.
            if self._broadcast_port is not None:
                broadcast_host = await self._binding.get_broadcast_address()
                self._inferred_broadcast_address = (
                    broadcast_host,
                    self._broadcast_port,
                )

        return sock

    async def _bind_socket(self, sock: SocketType) -> None:
        """Binds the given UDP socket to the address where it should listen for
        incoming UDP packets.
        """
        address = await self._binding.resolve()
        await sock.bind(address)

    async def _close(self):
        """Closes the socket connection."""
        self._inferred_broadcast_address = None
        return await super()._close()

    def _get_capabilities(self) -> Capabilities:
        return {"can_broadcast": True, "can_receive": True, "can_send": True}

    @property
    def broadcast_address(self) -> Optional[IPAddressAndPort]:
        """The current broadcast address of the connection.

        Returns:
            the address where broadcast messages are to be sent on this
            connection _right now_, or ``None`` if there is no such address at
            the moment. The latter may happen if the connection is closed, but
            there might also be other reasons. Users of this property must
            anticipate ``None`` and handle it accordingly.
        """
        return (
            self._user_defined_broadcast_address
            if self._user_defined_broadcast_address is not None
            else self._inferred_broadcast_address
        )

    async def broadcast(self, data: Union[bytes, tuple[bytes, IPAddressAndPort]]):
        """Broadcasts the given data on the connection.

        Parameters:
            data: the bytes to write to the broadcast address of the connection,
                or a tuple consisting of the bytes to broadcast and an address
                (which will be ignored). Tuples are supported to ensure that
                if you can call the `write()` method with an object, then you
                can also call `broadcast()` with it; downstream projects like
                `skybrush-server` may rely on this

        Raises:
            NoBroadcastAddressError: when there is no broadcast address
                associated to the connection
        """
        if isinstance(data, tuple):
            data, _ = data

        address = self.broadcast_address
        if address is None:
            raise NoBroadcastAddressError()
        else:
            return await self.write((data, address))

    def set_user_defined_broadcast_address(self, address: Optional[IPAddressAndPort]):
        """Sets the user-defined broadcast address of the connection.

        User-defined broadcast address take precedence over the default (inferred)
        broadcast address of the connection.

        Args:
            address: the address to set. Setting the address to ``None`` disables
                the user-defined address and returns to the default (inferred)
                broadcast address of the connection.
        """
        if not self._allow_broadcast and address is not None:
            raise RuntimeError("Broadcasts are disabled on this connection")

        self._user_defined_broadcast_address = address

    async def read(
        self, size: int = 4096, flags: int = 0
    ) -> tuple[bytes, Optional[IPAddressAndPort]]:
        """Reads some data from the connection.

        Parameters:
            size: the maximum number of bytes to return
            flags: flags to pass to the underlying ``recvfrom()`` call;
                see the UNIX manual for details

        Returns:
            the received data and the address it was received from, or
            ``(b"", None)`` if there was nothing to read.
        """
        if self._socket is not None:
            data, addr = await self._socket.recvfrom(size, flags)
            if not data:
                # Remote side closed connection
                await self.close()
            return data, addr
        else:
            return (b"", None)

    async def write(self, data: tuple[bytes, IPAddressAndPort], flags: int = 0) -> None:
        """Writes the given data to the socket connection.

        Parameters:
            data: the bytes to write, and the address to write the data to
            flags: additional flags to pass to the underlying ``send()``
                or ``sendto()`` call; see the UNIX manual for details.
        """
        if self._socket is not None:
            buf, address = data
            try:
                await self._socket.sendto(buf, flags, address)
            except OSError as ex:
                if ex.errno == EADDRNOTAVAIL:
                    # Address not available any more. Maybe the interface
                    # has changed its address? We have seen this on macOS for
                    # sure.
                    await self.close()
                raise
        else:
            raise RuntimeError("connection does not have a socket")


@create_connection.register("udp-broadcast")
def _create_udp_broadcast_connection(*args, **kwds):
    """Helper function that creates a UDP broadcast connection with
    UDPListenerConnection_.
    """
    kwds["allow_broadcast"] = True
    return UDPListenerConnection(*args, **kwds)


@create_connection.register("udp-broadcast-in")
class BroadcastUDPListenerConnection(UDPListenerConnection):
    """Connection object that binds to the broadcast address of a given
    subnet or a given interface and listens for incoming packets from there.

    The connection is for inbound packets only; it cannot be used for sending
    packets.
    """

    can_send: bool = False
    """Marker that indicates that the connection should not be used for sending
    data.

    Deprecated; use `get_capabilities()` instead.
    """

    def __init__(self, interface: Optional[str] = None, port: int = 0, **kwds):
        """Constructor.

        Parameters:
            interface: name of the network interface whose broadcast
                address to bind to, or a subnet in slashed notation whose
                broadcast address to bind to
            port: the port number that the socket will bind (or
                connect) to. Zero means that the socket will choose a random
                ephemeral port number on its own.

        Keyword arguments:
            path (str): convenience alias for `interface` so we can use this class
                with `create_connection.register()`
        """
        if interface is None:
            interface = kwds.get("path")
            if interface is None:
                raise ValueError("either 'interface' or 'path' must be given")
            else:
                interface = str(interface)

        if "/" in interface:
            # We are probably given a subnet
            super().__init__(subnet=interface, port=port)
        else:
            # We are probably given a network interface name
            super().__init__(interface=interface, port=port)

        # Instruct the binding to bind to the broadcast address
        self._binding.bind_to_broadcast()

    def _get_capabilities(self) -> Capabilities:
        return {"can_broadcast": True, "can_receive": True, "can_send": True}


@create_connection.register("udp-multicast")
class MulticastUDPListenerConnection(UDPListenerConnection):
    """Connection object that uses a multicast UDP socket.

    The connection cannot be used for sending packets.
    """

    can_send: bool = False
    """Marker that indicates that the connection should not be used for sending
    data.

    Deprecated; use `get_capabilities()` instead.
    """

    def __init__(
        self,
        group: Optional[str] = None,
        port: int = 0,
        interface: Optional[str] = None,
        **kwds,
    ):
        """Constructor.

        Parameters:
            group: the IP address of the multicast group that the socket will
                bind to.
            port: the port number that the socket will bind (or connect) to. Zero
                means that the socket will choose a random ephemeral port number
                on its own.
            interface: name of the network interface to bind the socket to.
                `None` means to bind to the default network interface where
                multicast is supported.

        Keyword arguments:
            host (str): convenience alias for `group` so we can use this class
                with `create_connection.register()`
        """
        if group is None:
            group = kwds.get("host")
            if group is None:
                raise ValueError("either 'group' or 'host' must be given")

        if not ip_address(group).is_multicast:
            raise ValueError("expected multicast group address")

        super().__init__(host=group, port=port)

        self._interface = interface

    async def _create_and_open_socket(self):
        """Creates a new non-blocking reusable UDP socket that is not bound
        anywhere yet.
        """
        sock = await super()._create_and_open_socket()

        if self._interface:
            address = await to_thread.run_sync(
                resolve_network_interface_or_address, self._interface
            )
        else:
            address = "0.0.0.0"

        assert self._address is not None

        host, _ = self._address
        req = struct.pack("4s4s", inet_aton(host), inet_aton(address))
        sock.setsockopt(IPPROTO_IP, IP_ADD_MEMBERSHIP, req)

        return sock

    def _get_capabilities(self) -> Capabilities:
        return {"can_broadcast": True, "can_receive": True, "can_send": True}


@create_connection.register("udp-subnet")
class SubnetBindingUDPListenerConnection(UDPListenerConnection):
    """Connection object that enumerates the IP addresses of the network
    interfaces and creates a UDP listener connection bound to the network
    interface that is within a given subnet.

    If there are multiple network interfaces that match the given subnet,
    the connection binds to the first one it finds.

    The connection allows broadcasts by default, unlike a regular UDP
    listener connection, which does not.
    """

    def __init__(
        self,
        network: Optional[Union[IPv4Network, IPv6Network, str]] = None,
        port: int = 0,
        **kwds,
    ):
        """Constructor.

        Parameters:
            network: an IPv4 or IPv6 network object that describes the subnet
                that the connection tries to bind to, or its string representation
            port: the port number to which the newly created sockets will be
                bound to. Zero means to pick an ephemeral port number randomly.

        Keyword arguments:
            path (str): convenience alias for `network` so we can use this class
                with `create_connection.register()`
        """
        if network is None:
            if "path" in kwds:
                network = str(kwds["path"])
            else:
                raise ValueError("either 'network' or 'path' must be given")

        if "allow_broadcast" not in kwds:
            kwds["allow_broadcast"] = True

        super().__init__(subnet=network, port=port, **kwds)


@create_connection.register("unix")
class UnixDomainSocketConnection(StreamConnectionBase):
    """Connection object that wraps a Trio-based Unix domain socket stream."""

    def __init__(self, path: str, **kwds):
        """Constructor.

        Parameters:
            path: the path to connect to
        """
        super().__init__()
        self._path = path

    async def _create_stream(self) -> SocketStream:
        try:
            from trio.socket import AF_UNIX
        except ImportError:
            raise RuntimeError(
                "UNIX domain sockets are not supported on this platform"
            ) from None

        sock = socket(AF_UNIX, SOCK_STREAM)
        await sock.connect(self._path)
        return SocketStream(sock)

    @property
    def path(self) -> str:
        """Returns the path of the socket."""
        return self._path
