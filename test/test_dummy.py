from trio import move_on_after

from flockwave.connections import DummyConnection, create_connection
from flockwave.connections.middleware import LoggingMiddleware


async def test_dummy_open_close():
    conn = DummyConnection()

    assert conn.is_disconnected
    await conn.open()
    assert conn.is_connected
    await conn.close()
    assert conn.is_disconnected


async def test_dummy_context_manager():
    conn = DummyConnection()

    assert conn.is_disconnected

    async with conn:
        assert conn.is_connected

    assert conn.is_disconnected


async def test_dummy_create_with_factory():
    assert isinstance(create_connection("dummy"), DummyConnection)


async def test_dummy_create_with_factory_and_middleware():
    logger = LoggingMiddleware.create()
    with create_connection.use_middleware(logger, "log"):
        assert isinstance(create_connection("dummy+log"), DummyConnection)


async def test_dummy_write():
    conn = DummyConnection()
    await conn.open()
    await conn.write(b"foobar")
    await conn.close()


async def test_dummy_read(autojump_clock):
    conn = DummyConnection()
    await conn.open()

    read_succeeded = False
    with move_on_after(5):
        await conn.read()
        read_succeeded = True

    assert not read_succeeded
    await conn.close()
