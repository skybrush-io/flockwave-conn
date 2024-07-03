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
from typing import cast, Optional, Union

from flockwave.networking import (
    create_socket,
    find_interfaces_in_network,
    get_broadcast_address_of_network_interface,
    resolve_network_interface_or_address,
)

from .base import (
    ConnectionBase,
    ListenerConnection,
    RWConnection,
)
from .errors import ConnectionError
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
    of an IP address and a port."""

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
        if self._socket is None:
            # No socket yet; try to obtain the address from the "_address"
            # property instead
            if self._address is None:
                raise ValueError("socket is not open yet")
            else:
                return super().address
        else:
            # Ask the socket for its address
            return self._socket.getsockname()  # type: ignore

    @property
    def socket(self):
        """Returns the socket object itself."""
        return self._socket

    async def _close(self):
        """Closes the socket connection."""
        self._socket.close()  # type: ignore
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

    _address: IPAddressAndPort
    _backlog: int

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
        await self._bind_socket(sock)
        if self._backlog >= 0:
            sock.listen(self._backlog)
        else:
            sock.listen()
        return cast(SocketType, sock)

    async def _bind_socket(self, sock) -> None:
        """Binds the given TCP socket to the address where it should listen for
        incoming TCP connections.
        """
        await sock.bind(self._address)

    async def accept(self) -> IncomingTCPStreamConnection:
        client_socket, address = await self._socket.accept()  # type: ignore
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
            data = await self._socket.recv(size, flags)  # type: ignore
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
            await self._socket.send(data, flags)  # type: ignore
        else:
            raise RuntimeError("connection does not have a socket")


@create_connection.register("udp-listen")
class UDPListenerConnection(
    SocketConnectionBase,
    RWConnection[tuple[bytes, IPAddressAndPort], tuple[bytes, IPAddressAndPort]],
):
    """Connection object that uses a UDP socket that listens on a specific
    IP address and port.

    The socket can also be used for sending data to arbitrary IP addresses and
    ports. However, this means that the objects being sent on this socket are
    actually tuples containing the raw data _and_ the address to send the data
    to.
    """

    _address: IPAddressAndPort
    _allow_broadcast: bool
    _broadcast_interface: Optional[str]
    _broadcast_port: Optional[int]
    _multicast_interface: Optional[str]
    _multicast_ttl: Optional[int]

    def __init__(
        self,
        host: Optional[str] = "",
        port: int = 0,
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
        self._address = (host or "", port or 0)
        self._allow_broadcast = bool(int(allow_broadcast))
        self._broadcast_interface = broadcast_interface
        self._broadcast_port = (
            int(broadcast_port) if broadcast_port is not None else None
        )
        self._multicast_interface = multicast_interface
        self._multicast_ttl = int(multicast_ttl) if multicast_ttl is not None else None

        if self._broadcast_port is not None:
            self._allow_broadcast = True

    async def _create_and_open_socket(self):
        """Creates a new non-blocking reusable UDP socket that is not bound
        anywhere yet.
        """
        sock = create_socket(SOCK_DGRAM)

        if self._allow_broadcast:
            sock.setsockopt(SOL_SOCKET, SO_BROADCAST, 1)
            if self._broadcast_interface is not None:
                try:
                    from socket import IP_BROADCAST_IF  # type: ignore
                except ImportError:
                    raise RuntimeError(
                        "this OS does not support setting the broadcast interface of a socket"
                    ) from None
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

        # Assign the broadcast address to this socket if the user hasn't assigned
        # one yet
        if self._allow_broadcast:
            # Note that we need to do this here; by the time we get here, we
            # already have our definite port number even if originally it was
            # defined as zero (i.e. the OS should pick one)
            if self._broadcast_port is None:
                new_address = sock.getsockname()
                if isinstance(new_address, tuple) and len(new_address) > 1:
                    self._broadcast_port = new_address[1]

            # Do not overwrite any user-defined broadcast address
            if (
                getattr(self, "broadcast_address", None) is None
                and self._broadcast_port is not None
            ):
                self.broadcast_address = ("255.255.255.255", self._broadcast_port)

        return sock

    async def _bind_socket(self, sock) -> None:
        """Binds the given UDP socket to the address where it should listen for
        incoming UDP packets.
        """
        await sock.bind(self._address)

    async def read(
        self, size: int = 4096, flags: int = 0
    ) -> tuple[bytes, Optional[IPAddressAndPort]]:
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
            data, addr = await self._socket.recvfrom(size, flags)  # type: ignore
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
            await self._socket.sendto(buf, flags, address)  # type: ignore
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

    The connection cannot be used for sending packets.
    """

    can_send: bool = False

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
class MulticastUDPListenerConnection(UDPListenerConnection):
    """Connection object that uses a multicast UDP socket.

    The connection cannot be used for sending packets.
    """

    can_send: bool = False

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


@create_connection.register("udp-subnet")
class SubnetBindingUDPListenerConnection(UDPListenerConnection):
    """Connection object that enumerates the IP addresses of the network
    interfaces and creates a UDP listener connection bound to the network
    interface that is within a given subnet.

    If there are multiple network interfaces that match the given subnet,
    the connection binds to the first one it finds.
    """

    _broadcast_address: Optional[IPAddressAndPort]
    _broadcast_address_from_network: Optional[IPAddressAndPort]
    _network: Union[IPv4Network, IPv6Network]

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
            network = kwds.get("path")
            if network is None:
                raise ValueError("either 'network' or 'path' must be given")

        super().__init__(port=port, **kwds)

        self._broadcast_address = None
        self._network = ip_network(network)

        if self._broadcast_port is not None:
            self._broadcast_address_from_network = (
                str(self._network.broadcast_address),
                self._broadcast_port,
            )
        else:
            self._broadcast_address_from_network = None

    async def _bind_socket(self, sock) -> None:
        """Binds the given UDP socket to the address where it should listen for
        incoming UDP packets.
        """
        interfaces = find_interfaces_in_network(self._network)
        if not interfaces:
            raise ConnectionError("no network interface in the given network")

        if self._address is None:
            raise RuntimeError("UDP socket has no associated port")

        self._address = (interfaces[0][1], self._address[1])
        return await super()._bind_socket(sock)

    @property
    def broadcast_address(self) -> Optional[IPAddressAndPort]:
        """The broadcast address of the subnet."""
        return (
            self._broadcast_address
            if self._broadcast_address is not None
            else self._broadcast_address_from_network
        )

    @broadcast_address.setter
    def broadcast_address(self, value: Optional[IPAddressAndPort]):
        self._broadcast_address = value


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
