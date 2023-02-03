from flockwave.connections import create_loopback_connection_pair


async def test_loopback_read_write():
    foo, bar = create_loopback_connection_pair(int, 1)

    await foo.open()
    await bar.open()

    await foo.write(1)
    assert await bar.read() == 1

    await foo.write(2)
    assert await bar.read() == 2

    await bar.write(3)
    assert await foo.read() == 3

    await foo.close()
    await bar.close()
