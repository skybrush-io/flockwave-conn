from flockwave.connections import create_connection, DummyConnection


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
