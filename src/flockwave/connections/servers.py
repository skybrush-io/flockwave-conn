"""Asynchronous tasks that serve connections over TCP, Unix domain sockets
or other protocols.
"""

import os
import stat

from math import inf
from socket import socket
from typing import Awaitable, Callable, Optional
from uuid import uuid4

from trio import (
    Nursery,
    SocketListener,
    SocketStream,
    TASK_STATUS_IGNORED,
    fail_after,
    serve_listeners,
    serve_tcp,
    to_thread,
)
from trio.abc import Listener
from trio.socket import from_stdlib_socket

__all__ = ("open_unix_listeners", "serve_tcp", "serve_unix")


# _compute_backlog() is copied from Trio; see its documentation and the
# reasoning behind the default choice there
def _compute_backlog(backlog):
    if backlog is None:
        backlog = inf
    return min(backlog, 0xFFFF)


class UnixSocketListener(Listener[SocketStream]):
    """Specialized SocketListener_ that unlinks the associated socket after
    the listener is closed.
    """

    def __init__(self, socket, path: str, inode: int):
        socket = from_stdlib_socket(socket)

        self._wrapped_listener = SocketListener(socket)

        self.path = path
        self.inode = inode

    @staticmethod
    def _create(path: str, mode: int, backlog: int):
        try:
            from socket import AF_UNIX
        except ImportError:
            raise RuntimeError(
                "UNIX domain sockets are not supported on this platform"
            ) from None

        if os.path.exists(path) and not stat.S_ISSOCK(os.stat(path).st_mode):
            raise FileExistsError(f"Existing file is not a socket: {path}")

        sock = socket(AF_UNIX)
        try:
            # Using umask prevents others tampering with the socket during creation.
            # Unfortunately it also might affect other threads and signal handlers.
            tmp_path = f"{path}.{uuid4().hex[:8]}"
            old_mask = os.umask(0o777)
            try:
                sock.bind(tmp_path)
            finally:
                os.umask(old_mask)
            try:
                inode = os.stat(tmp_path).st_ino
                os.chmod(tmp_path, mode)  # os.fchmod doesn't work on sockets on MacOS
                sock.listen(backlog)
                os.rename(tmp_path, path)
            except:  # noqa
                os.unlink(tmp_path)
                raise
        except:  # noqa
            sock.close()
            raise
        return UnixSocketListener(sock, path, inode)

    @staticmethod
    async def create(path, *, mode: int = 0o666, backlog: Optional[int] = None):
        return await to_thread.run_sync(
            UnixSocketListener._create, path, mode, backlog or 0xFFFF
        )

    async def accept(self):
        return await self._wrapped_listener.accept()

    async def aclose(self) -> None:
        with fail_after(1) as cleanup:
            cleanup.shield = True
            await self._wrapped_listener.aclose()
            self._close()

    @property
    def socket(self):
        return self._wrapped_listener.socket

    def _close(self) -> None:
        try:
            from socket import AF_UNIX
        except ImportError:
            raise RuntimeError(
                "UNIX domain sockets are not supported on this platform"
            ) from None

        try:
            # Test connection
            s = socket(AF_UNIX)
            try:
                s.connect(self.path)
            except ConnectionRefusedError:
                if self.inode == os.stat(self.path).st_ino:
                    os.unlink(self.path)
            finally:
                s.close()
        except Exception:
            pass


async def open_unix_listeners(
    path: str, *, mode: int = 0o666, backlog: Optional[int] = None
):
    """Creates a :class:`SocketListener` object to listen on a UNIX domain
    socket.

    Args:
        path: The path to listen on. When it exists and is already a socket,
            it will be removed unless ``unlink`` is set to ``False``.
        mode: The mode of the UNIX domain socket.
        backlog: The listen backlog to use. If you leave this as ``None`` then
            Trio will pick a good default. (Currently: whatever your system has
            configured as the maximum backlog.)

    Returns:
        a single :class:`UnixSocketListener`, wrapped in a list
    """
    return [await UnixSocketListener.create(path, mode=mode, backlog=backlog)]


async def serve_unix(
    handler: Callable[[SocketStream], Awaitable[None]],
    path: str,
    *,
    mode: int = 0o666,
    backlog: Optional[int] = None,
    handler_nursery: Optional[Nursery] = None,
    task_status=TASK_STATUS_IGNORED,
):
    """Listen for incoming connections on a given UNIX domain socket, and for
    each one start a task running ``handler(stream)``.

    This is a thin convenience wrapper around :func:`open_unix_listener()` and
    :func:`serve_listeners()` - see them for full details.

    .. warning::

       If ``handler`` raises an exception, then this function doesn't do
       anything special to catch it – so by default the exception will
       propagate out and crash your server. If you don't want this, then catch
       exceptions inside your ``handler``, or use a ``handler_nursery`` object
       that responds to exceptions in some other way.

    Args:
        handler: The handler to start for each incoming connection. Passed to
            :func:`serve_listeners`.
        path: The path to listen on. Passed to :func:`open_tcp_listeners`.
        mode: The mode of the UNIX domain socket.
        backlog: The listen backlog, or None to have a good default picked.
            Passed to :func:`open_unix_listeners`.
        handler_nursery: The nursery to start handlers in, or None to use an
            internal nursery. Passed to :func:`serve_listeners`.
        task_status: This function can be used with ``nursery.start``.

    Returns:
        This function only returns when cancelled.
    """

    listeners = await open_unix_listeners(path, mode=mode, backlog=backlog)
    await serve_listeners(
        handler, listeners, handler_nursery=handler_nursery, task_status=task_status
    )
