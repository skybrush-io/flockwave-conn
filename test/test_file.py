from flockwave.connections.file import FileConnection


async def test_read_from_file_connection(tmp_path):
    tmp_file = tmp_path / "test.txt"
    tmp_file.write_bytes(b"foobarspam")

    conn = FileConnection(tmp_file, "rb")

    await conn.open()
    assert (await conn.read(3)) == b"foo"
    assert (await conn.read()) == b"barspam"
    await conn.close()


async def test_write_to_file_connection(tmp_path):
    tmp_file = tmp_path / "test.txt"
    conn = FileConnection(tmp_file, "wb")

    await conn.open()
    await conn.write(b"foobar")
    await conn.write(b"spam")
    await conn.close()

    assert tmp_file.read_bytes() == b"foobarspam"
