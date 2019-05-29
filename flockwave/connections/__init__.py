"""Package that holds classes that implement connections to various
types of devices: serial ports, files, TCP sockets and so on.

Each connection class provided by this package has a common notion of a
*state*, which may be one of: disconnected, connecting, connected or
disconnecting. Connection instances send signals when their state changes.
"""

from .base import Connection, ConnectionBase, ConnectionState
from .factory import ConnectionFactory, create_connection

__all__ = ("Connection", "ConnectionBase", "ConnectionFactory",
           "ConnectionState", "create_connection")
