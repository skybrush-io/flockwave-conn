"""Connections via TCP or UDP sockets."""

from __future__ import absolute_import, print_function

import struct

from abc import abstractmethod
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
from typing import Optional, Tuple, Union

from .base import (
    ConnectionBase,
    ListenerConnection,
    ReadableConnection,
    WritableConnection,
)
from .errors import ConnectionError
from .factory import create_connection
from .stream import StreamConnectionBase
from .types import IPAddressAndPort

from flockwave.networking import (
    create_socket,
    find_interfaces_in_network,
    get_broadcast_address_of_network_interface,
    resolve_network_interface_or_address,
)

__all__ = (
    "BroadcastUDPSocketConnection",
    "MulticastUDPSocketConnection",
    "TCPListenerConnection",
    "TCPStreamConnection",
    "UDPSocketConnection",
    "UnixDomainSocketConnection",
)


class InternetAddressMixin:
    """Mixin class that adds an "address" property to a connection, consisting
    of an IP address and a port."""

    def __init__(self):
        self._address = None

    @property
    def address(self):
        """Returns the IP address and port of the socket, in the form of a
        tuple.
        """
        return self._address

    @property
    def ip(self):
        """Returns the IP address that the socket is bound to."""
        return self.address[0]

    @property
    def port(self):
        """Returns the port that the socket is bound to."""
        return self.address[1]


class SocketConnectionBase(ConnectionBase, InternetAddressMixin):
    """Base class for connection objects using TCP or UDP sockets."""

    def __init__(self):
        ConnectionBase.__init__(self)
        InternetAddressMixin.__init__(self)
        self._socket = None

    @InternetAddressMixin.address.getter
    def address(self):
        """Returns the IP address and port of the socket, in the form of a
        tuple.
        """
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
        self._socket.close()
        self._socket = None

    @abstractmethod
    async def _create_and_open_socket(self) -> SocketType:
        """Creates and opens the socket that the connection will use."""
        raise NotImplementedError

    async def _open(self):
        """Opens the socket connection."""
        self._socket = await self._create_and_open_socket()

    def _extract_address(self, address):
        """Extracts the *real* IP address and port from the given object.
        The object may be a SocketConnectionBase_, a tuple consisting
        of the IP address and port, or ``None``. Returns a tuple consisting
        of the IP address and port or ``None``.
        """
        if isinstance(address, SocketConnectionBase):
            address = address.address
        return address


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
        self._address = (host or "", port or 0)

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

    def __init__(self, address, socket: SocketType):
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


@create_connection.register("tcp-listener")
class TCPListenerConnection(
    SocketConnectionBase, ListenerConnection[IncomingTCPStreamConnection]
):
    """Connection object that wraps a Trio TCP listener that listens for
    incoming TCP connections on a specific port.
    """

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
        self._address = (host or "", port or 0)
        self._backlog = backlog

    async def _create_and_open_socket(self) -> SocketType:
        """Creates and opens the socket that the connection will use."""
        sock = create_socket(SOCK_STREAM)
        if self._backlog >= 0:
            sock.listen(self._backlog)
        else:
            sock.listen()
        return sock

    async def _bind_socket(self, sock) -> None:
        """Binds the given TCP socket to the address where it should listen for
        incoming TCP connections.
        """
        await sock.bind(self._address)

    async def accept(self) -> IncomingTCPStreamConnection:
        client_socket, address = await self._socket.accept()
        connection = IncomingTCPStreamConnection(address, client_socket)
        await connection.open()
        return connection


@create_connection.register("udp")
class UDPSocketConnection(
    SocketConnectionBase,
    ReadableConnection[Tuple[bytes, IPAddressAndPort]],
    WritableConnection[Tuple[bytes, IPAddressAndPort]],
):
    """Connection object that uses a UDP socket."""

    def __init__(
        self,
        host: Optional[str] = "",
        port: int = 0,
        allow_broadcast: bool = False,
        broadcast_interface: Optional[str] = None,
        multicast_interface: Optional[str] = None,
        multicast_ttl: Optional[int] = None,
        **kwds,
    ):
        """Constructor.

        Parameters:
            host: the IP address or hostname that the socket will bind to. The
                default value means that the socket will bind to all IP
                addresses of the local machine.
            port: the port number that the socket will bind to. Zero means that
                the socket will choose a random ephemeral port number on its
                own.
            allow_broadcast: whether to allow the socket to send broadcast
                packets. Note that if you want to receive broadcast packets as
                well as sending them, the host needs to be set to the empty
                string (representing "all interfaces") because broadcast packets
                arrive on a different address than unicast packets
            broadcast_interface: the name or IP address of the network interface
                on which broadcast packets should be sent from this socket.
                Applies only if ``allow_broadcast`` is truthy. ``None`` means
                to use the default setting of the OS.
            multicast_interface: the name or IP address of the network interface
                on which multicast packets should be sent from this socket.
                ``None`` means not to configure the multicast interface for
                this socket.
            multicast_ttl: the TTL (time-to-live) value of multicast packets
                sent from this socket. ``None`` means not to configure the
                TTL value of outbound packets.
        """
        super().__init__()
        self._address = (host or "", port or 0)
        self._allow_broadcast = bool(int(allow_broadcast))
        self._broadcast_interface = broadcast_interface
        self._multicast_interface = multicast_interface
        self._multicast_ttl = int(multicast_ttl) if multicast_ttl is not None else None

    async def _create_and_open_socket(self):
        """Creates a new non-blocking reusable UDP socket that is not bound
        anywhere yet.
        """
        sock = create_socket(SOCK_DGRAM)

        if self._allow_broadcast:
            sock.setsockopt(SOL_SOCKET, SO_BROADCAST, 1)
            if self._broadcast_interface is not None:
                try:
                    from socket import IP_BROADCAST_IF
                except ImportError:
                    raise RuntimeError(
                        "this OS does not support setting the broadcast interface of a socket"
                    )
                broadcast_interface = await to_thread.run_sync(
                    resolve_network_interface_or_address, self._broadcast_interface
                )
                sock.setsockopt(
                    IPPROTO_IP, IP_BROADCAST_IF, inet_aton(broadcast_interface)
                )

        if self._multicast_ttl is not None:
            sock.setsockopt(IPPROTO_IP, IP_MULTICAST_TTL, self._multicast_ttl)
        if self._multicast_interface is not None:
            multicast_interface = await to_thread.run_sync(
                resolve_network_interface_or_address, self._multicast_interface
            )
            sock.setsockopt(IPPROTO_IP, IP_MULTICAST_IF, inet_aton(multicast_interface))

        await self._bind_socket(sock)

        return sock

    async def _bind_socket(self, sock):
        """Binds the given UDP socket to the address where it should listen for
        incoming UDP packets.
        """
        await sock.bind(self._address)

    async def read(self, size: int = 4096, flags: int = 0):
        """Reads some data from the connection.

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
            data, addr = await self._socket.recvfrom(size, flags)
            if not data:
                # Remote side closed connection
                await self.close()
            return data, addr
        else:
            return (b"", None)

    async def write(self, data: Tuple[bytes, IPAddressAndPort], flags: int = 0) -> None:
        """Writes the given data to the socket connection.

        Parameters:
            data: the bytes to write, and the address to write the data to
            flags: additional flags to pass to the underlying ``send()``
                or ``sendto()`` call; see the UNIX manual for details.
        """
        if self._socket is not None:
            data, address = data
            await self._socket.sendto(data, flags, address)
        else:
            raise RuntimeError("connection does not have a socket")


@create_connection.register("udp-broadcast")
def _create_udp_broadcast_connection(*args, **kwds):
    """Helper function that creates a UDP broadcast connection with
    UDPSocketConnection_.
    """
    kwds["allow_broadcast"] = True
    return UDPSocketConnection(*args, **kwds)


@create_connection.register("udp-broadcast-in")
class BroadcastUDPSocketConnection(UDPSocketConnection):
    """Connection object that binds to the broadcast address of a given
    subnet or a given interface and listens for incoming packets from there.

    The connection cannot be used for sending packets.
    """

    can_send = False

    def __init__(self, interface=None, port=0, **kwds):
        """Constructor.

        Parameters:
            interface (str): name of the network interface whose broadcast
                address to bind to, or a subnet in slashed notation whose
                broadcast address to bind to
            port (int): the port number that the socket will bind (or
                connect) to. Zero means that the socket will choose a random
                ephemeral port number on its own.

        Keyword arguments:
            path (str): convenience alias for `interface` so we can use this class
                with `create_connection.register()`
        """
        interface = interface or kwds.get("path")

        if interface is None:
            address = "255.255.255.255"
        else:
            try:
                network = ip_network(interface)
                address = str(network.broadcast_address)
            except ValueError:
                # Not an IPv4 network in slashed notation; try it as an
                # interface name
                address = get_broadcast_address_of_network_interface(interface)

        super().__init__(host=address, port=port)


@create_connection.register("udp-multicast")
class MulticastUDPSocketConnection(UDPSocketConnection):
    """Connection object that uses a multicast UDP socket.

    The connection cannot be used for sending packets.
    """

    can_send = False

    def __init__(self, group=None, port=0, interface=None, **kwds):
        """Constructor.

        Parameters:
            group (str): the IP address of the multicast group that the socket
                will bind to.
            port (int): the port number that the socket will bind (or
                connect) to. Zero means that the socket will choose a random
                ephemeral port number on its own.
            interface (Optional[str]): name of the network interface to bind
                the socket to. `None` means to bind to the default network
                interface where multicast is supported.

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

        host, _ = self._address
        req = struct.pack("4s4s", inet_aton(host), inet_aton(address))
        sock.setsockopt(IPPROTO_IP, IP_ADD_MEMBERSHIP, req)

        return sock


@create_connection.register("udp-subnet")
class SubnetBindingUDPSocketConnection(UDPSocketConnection):
    """Connection object that enumerates the IP addresses of the network
    interfaces and creates a UDP or TCP socket connection bound to the
    network interface that is within a given subnet.

    If there are multiple network interfaces that match the given subnet,
    the connection binds to the first one it finds.
    """

    def __init__(
        self,
        network: Optional[Union[IPv4Network, IPv6Network, str]] = None,
        port: int = 0,
        **kwds,
    ):
        """Constructor.

        Parameters:
            network (Union[IPv4Network, IPv6Network, str]): an IPv4 or IPv6 network
                object that describes the subnet that the connection tries to bind
                to, or its string representation
            port (int): the port number to which the newly created sockets will
                be bound to. Zero means to pick an ephemeral port number
                randomly.

        Keyword arguments:
            path (str): convenience alias for `network` so we can use this class
                with `create_connection.register()`
        """

        if network is None:
            network = kwds.get("path")
            if network is None:
                raise ValueError("either 'network' or 'path' must be given")

        super().__init__(port=port, **kwds)

        self._network = ip_network(network)

    async def _bind_socket(self, sock):
        """Binds the given UDP socket to the address where it should listen for
        incoming UDP packets.
        """
        interfaces = find_interfaces_in_network(self._network)
        if not interfaces:
            raise ConnectionError("no network interface in the given network")

        self._address = (interfaces[0][1], self._address[1])
        return await super()._bind_socket(sock)

    @property
    def broadcast_address(self):
        """The broadcast address of the subnet."""
        return self._network.broadcast_address


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

    async def _create_stream(self):
        try:
            from trio.socket import AF_UNIX
        except ImportError:
            raise RuntimeError("UNIX domain sockets are not supported on this platform")

        sock = socket(AF_UNIX, SOCK_STREAM)
        await sock.connect(self._path)
        return SocketStream(sock)

    @property
    def path(self) -> str:
        """Returns the path of the socket."""
        return self._path
