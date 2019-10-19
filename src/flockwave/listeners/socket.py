from trio import serve_tcp

from .base import TrioListenerBase
from .factory import create_listener

from ..connections.servers import serve_unix

__all__ = ("TCPSocketListener", "UnixDomainSocketListener")


@create_listener.register("tcp")
class TCPSocketListener(TrioListenerBase):
    """Listener that listens for incoming connections on a given TCP host
    and port.
    """

    def __init__(self, host: str = "", port: int = 0, **kwds):
        """Constructor.

        Parameters:
            host: the IP address or hostname that the socket will bind to. The
                default value means that the socket will bind to all IP
                addresses of the local machine.
            port: the port number that the socket will bind to. Zero means that
                the socket will choose a random ephemeral port number on its
                own.
        """
        super().__init__(**kwds)
        self._host = host
        self._port = port

    async def _run(self, handler, task_status) -> None:
        await serve_tcp(handler, self._port, host=self._host, task_status=task_status)


@create_listener.register("unix")
class UnixDomainSocketListener(TrioListenerBase):
    """Listener that listens for incoming connections on a given Unix domain
    socket.
    """

    def __init__(self, path: str, *, mode: int = 0o666, **kwds):
        """Constructor.

        Parameters:
            path: the path where the socket will be created.
            mode: the permissions of the newly created socket
        """
        super().__init__(**kwds)
        self._path = path
        self._mode = mode

    @property
    def mode(self) -> int:
        return self._mode

    @property
    def path(self) -> str:
        return self._path

    async def _run(self, handler, task_status) -> None:
        await serve_unix(handler, self._path, mode=self._mode, task_status=task_status)
