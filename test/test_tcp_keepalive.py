from flockwave.networking import create_socket, enable_tcp_keepalive

import trio.socket


async def test_tcp_keepalive():
    sock = create_socket(trio.socket.SOCK_STREAM)
    enable_tcp_keepalive(sock)
    assert (
        sock.getsockopt(trio.socket.SOL_SOCKET, trio.socket.SO_KEEPALIVE, 1) != b"\x00"
    )
