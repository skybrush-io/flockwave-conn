import sys

from flockwave.connections import ProcessConnection


async def test_process_connection_read(nursery):
    code = "for i in range(10): print('foo')"
    conn = ProcessConnection.create_in_nursery(nursery, [sys.executable, "-c", code])

    await conn.open()
    await conn.wait_until_connected()

    chunks = []
    while True:
        data = await conn.read()
        if not data:
            break

        chunks.append(data.replace(b"\r\n", b"\n"))

    assert b"".join(chunks) == b"foo\n" * 10

    await conn.close()
    await conn.wait_until_disconnected()


async def test_process_connection_echo(nursery):
    code = "while True: print(input())"
    conn = ProcessConnection.create_in_nursery(nursery, [sys.executable, "-c", code])

    await conn.open()
    await conn.wait_until_connected()

    await conn.write(b"foobar\n")
    await conn.write(b"baz\n")

    chunks = b""
    while b"baz\n" not in chunks:
        data = await conn.read()
        if not data:
            break

        chunks += data.replace(b"\r\n", b"\n")

    assert chunks == b"foobar\nbaz\n"

    await conn.close()
    await conn.wait_until_disconnected()
