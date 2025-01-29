"""Package that holds classes that implement connections to various
types of devices: serial ports, files, TCP sockets and so on.

Each connection class provided by this package has a common notion of a
*state*, which may be one of: disconnected, connecting, connected or
disconnecting. Connection instances send signals when their state changes.
"""

from .base import (
    BroadcastAddressOverride,
    BroadcastConnection,
    Connection,
    ConnectionBase,
    ConnectionState,
    ListenerConnection,
    ReadableConnection,
    RWConnection,
    WritableConnection,
)
from .capabilities import Capabilities, get_connection_capabilities
from .channel import ChannelConnection
from .dummy import DummyConnection
from .factory import (
    create_connection,
    create_connection_factory,
    create_loopback_connection_pair,
    register_builtin_middleware,
)
from .file import FileConnection
from .process import ProcessConnection
from .serial import SerialPortConnection
from .servers import open_unix_listeners, serve_unix
from .socket import (
    TCPListenerConnection,
    TCPStreamConnection,
    UDPListenerConnection,
    UDPSocketConnection,
    UnixDomainSocketConnection,
    MulticastUDPListenerConnection,
    BroadcastUDPListenerConnection,
)
from .stream import StreamConnection, StreamConnectionBase, StreamWrapperConnection
from .supervision import (
    ConnectionSupervisor,
    ConnectionTask,
    SupervisionPolicy,
    supervise,
)
from .types import IPAddressAndPort

__all__ = (
    "BroadcastAddressOverride",
    "BroadcastConnection",
    "BroadcastUDPListenerConnection",
    "Capabilities",
    "ChannelConnection",
    "Connection",
    "ConnectionBase",
    "ConnectionSupervisor",
    "ConnectionState",
    "ConnectionTask",
    "DummyConnection",
    "FileConnection",
    "IPAddressAndPort",
    "ListenerConnection",
    "MulticastUDPListenerConnection",
    "ProcessConnection",
    "ReadableConnection",
    "RWConnection",
    "SerialPortConnection",
    "StreamConnection",
    "StreamConnectionBase",
    "StreamWrapperConnection",
    "SupervisionPolicy",
    "TCPListenerConnection",
    "TCPStreamConnection",
    "UDPListenerConnection",
    "UDPSocketConnection",
    "UnixDomainSocketConnection",
    "WritableConnection",
    "create_connection",
    "create_connection_factory",
    "create_loopback_connection_pair",
    "get_connection_capabilities",
    "open_unix_listeners",
    "register_builtin_middleware",
    "serve_unix",
    "supervise",
)
