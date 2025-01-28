from pytest import raises
from trio import TooSlowError, fail_after

from flockwave.connections import create_loopback_connection_pair
from flockwave.connections.middleware import ReadOnlyMiddleware


async def test_read_only_middleware(autojump_clock):
    foo, bar = create_loopback_connection_pair(int, 1)
    bar_in = ReadOnlyMiddleware(bar)

    await foo.open()
    await bar_in.open()

    await foo.write(1)
    assert await bar_in.read() == 1

    await foo.write(2)
    assert await bar_in.read() == 2

    await bar_in.write(3)
    with raises(TooSlowError):
        with fail_after(3):
            await foo.read()

    await bar.write(3)
    assert await foo.read() == 3

    await foo.close()
    await bar_in.close()
