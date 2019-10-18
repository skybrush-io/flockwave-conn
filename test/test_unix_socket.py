import os

from flockwave.connections import UnixDomainSocketConnection, serve_unix
from pytest import raises
from trio import CancelScope, Event, move_on_after
from trio.socket import AF_UNIX, SOCK_STREAM, socket


def get_socket_path(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("u")  # make it as short as possible
    return str(
        tmp_path / "t"
    )  # same here; on macOS, it is easy to hit the socket path length limit


async def echo(stream):
    async with stream:
        data = await stream.receive_some()
        await stream.send_all(data)


async def test_unix_socket_connection_echo(nursery, tmp_path_factory, autojump_clock):
    socket_path = get_socket_path(tmp_path_factory)
    sender = UnixDomainSocketConnection(socket_path)

    with move_on_after(10):
        await nursery.start(serve_unix, echo, socket_path)

        async with sender:
            await sender.write(b"helo")
            data = await sender.read()
            assert data == b"helo"

    assert not os.path.exists(socket_path)


async def test_unix_socket_when_pathname_is_already_taken(nursery, tmp_path_factory):
    socket_path = get_socket_path(tmp_path_factory)
    with open(socket_path, "w") as fp:
        fp.write("placeholder")

    with raises(OSError, match="Existing file is not a socket"):
        await nursery.start(serve_unix, echo, socket_path)


async def test_unix_socket_cleanup_on_start(nursery, tmp_path_factory):
    socket_path = get_socket_path(tmp_path_factory)
    sock = socket(AF_UNIX, SOCK_STREAM)
    await sock.bind(socket_path)

    sender = UnixDomainSocketConnection(socket_path)
    scope = CancelScope()
    exited = Event()

    async def serve_unix_with_cancellation(task_status):
        with scope:
            await serve_unix(echo, socket_path, task_status=task_status)
        exited.set()

    with move_on_after(10):
        await nursery.start(serve_unix_with_cancellation)

        async with sender:
            await sender.write(b"helo")
            data = await sender.read()
            assert data == b"helo"

    scope.cancel()
    await exited.wait()

    assert not os.path.exists(socket_path)
