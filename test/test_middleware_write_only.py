from pytest import raises
from trio import TooSlowError, fail_after

from flockwave.connections import create_loopback_connection_pair
from flockwave.connections.middleware import WriteOnlyMiddleware


async def test_write_only_middleware(autojump_clock):
    foo, bar = create_loopback_connection_pair(int, 1)
    foo_out = WriteOnlyMiddleware(foo)

    await foo_out.open()
    await bar.open()

    await foo_out.write(1)
    assert await bar.read() == 1

    await foo_out.write(2)
    assert await bar.read() == 2

    await bar.write(3)
    with raises(TooSlowError):
        with fail_after(3):
            await foo_out.read()
    assert await foo.read() == 3

    await foo_out.close()
    await bar.close()
