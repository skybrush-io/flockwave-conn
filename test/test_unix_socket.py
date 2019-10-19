import os

from pytest import raises
from trio import move_on_after
from trio.socket import AF_UNIX, SOCK_STREAM, socket

from flockwave.connections import UnixDomainSocketConnection, serve_unix
from flockwave.listeners import UnixDomainSocketListener


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

    listener = UnixDomainSocketListener(socket_path, handler=echo, nursery=nursery)
    sender = UnixDomainSocketConnection(socket_path)

    with move_on_after(10):
        async with listener, sender:
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
    listener = UnixDomainSocketListener(socket_path, handler=echo, nursery=nursery)

    with move_on_after(10):
        async with listener, sender:
            await sender.write(b"helo")
            data = await sender.read()
            assert data == b"helo"

    await listener.close()

    assert not os.path.exists(socket_path)
