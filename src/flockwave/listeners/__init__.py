"""Package that holds classes that implement listeners for incoming connections
on various connection-oriented transports such as TCP sockets or Unix domain
sockets.

Listeners augment the notion of connections; the concept is that listeners
listen for incoming connections and then provide an appropriate connection
object to a handler function. The handler function is then responsible for
communicating on the connection using its standard methods.

Similarly to connection objects, listeners also have a standard lifecycle.
Listeners start from the "closed" state. When a listener is instructed to start
listening, it will first transition to the "preparing" state and then to the
"open" (listening) state. When a listener is instructed to shut down, it will
transition to the "closing" state and then move back to "closed". The "preparing"
and "closing" states are considered transient, while the "open" and "closed"
states are stable.
"""

from .base import Listener, ListenerBase, ListenerState
from .factory import create_listener, create_listener_factory
from .socket import UnixDomainSocketListener, TCPSocketListener

__all__ = (
    "Listener",
    "ListenerBase",
    "ListenerState",
    "UnixDomainSocketListener",
    "TCPSocketListener",
    "create_listener",
    "create_listener_factory",
)
