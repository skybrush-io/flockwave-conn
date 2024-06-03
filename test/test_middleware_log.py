from flockwave.connections import create_loopback_connection_pair
from flockwave.connections.middleware import LoggingMiddleware


async def test_log_read_write():
    foo, bar = create_loopback_connection_pair(bytes, 1)

    foo_log: list[str] = []
    bar_log: list[str] = []

    async with (
        LoggingMiddleware(foo, writer=foo_log.append) as foo_with_logging,
        LoggingMiddleware(bar, writer=bar_log.append) as bar_with_logging,
    ):
        assert isinstance(foo_with_logging, foo.__class__)
        assert isinstance(bar_with_logging, bar.__class__)

        await foo_with_logging.write(b"hello world\x01\x02\x03")
        data = await bar_with_logging.read()

        assert data == b"hello world\x01\x02\x03"

        await foo_with_logging.write(b"this is a longer string")
        data = await bar_with_logging.read()

        assert data == b"this is a longer string"

    assert foo_log == [
        "-->  68 65 6C 6C 6F 20 77 6F  72 6C 64 01 02 03        hello world...",
        "-->  74 68 69 73 20 69 73 20  61 20 6C 6F 6E 67 65 72  this is a longer",
        "-->  20 73 74 72 69 6E 67                               string",
    ]
    assert bar_log == [
        "<--  68 65 6C 6C 6F 20 77 6F  72 6C 64 01 02 03        hello world...",
        "<--  74 68 69 73 20 69 73 20  61 20 6C 6F 6E 67 65 72  this is a longer",
        "<--  20 73 74 72 69 6E 67                               string",
    ]
