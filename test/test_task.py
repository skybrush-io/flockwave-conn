from flockwave.connections.base import TaskConnectionBase
from pytest import raises
from trio import sleep_forever


class DummyTaskConnection(TaskConnectionBase):
    def __init__(self):
        super().__init__()
        self.running = False

    async def _run(self, started):
        self.running = True
        started()
        try:
            await sleep_forever()
        finally:
            self.running = False


async def test_task_open_close(nursery):
    conn = DummyTaskConnection()

    assert conn.is_disconnected
    assert not conn.running

    with raises(RuntimeError, match="assign a nursery"):
        await conn.open()

    conn.assign_nursery(nursery)
    await conn.open()

    assert conn.is_connected
    assert conn.running

    await conn.close()

    assert conn.is_disconnected
    assert not conn.running
