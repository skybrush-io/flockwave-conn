"""Package that holds classes that implement connections to various
types of devices: serial ports, files, TCP sockets and so on.

Each connection class provided by this package has a common notion of a
*state*, which may be one of: disconnected, connecting, connected or
disconnecting. Connection instances send signals when their state changes.
"""

from .base import (
    Connection,
    ConnectionBase,
    ConnectionState,
    ListenerConnection,
    ReadableConnection,
    RWConnection,
    WritableConnection,
)
from .dummy import DummyConnection
from .factory import create_connection, create_connection_factory
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
    "BroadcastUDPListenerConnection",
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
    "open_unix_listeners",
    "serve_unix",
    "supervise",
)
