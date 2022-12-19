from flockwave.connections.base import TaskConnectionBase
from pytest import raises
from trio import sleep, sleep_forever


class DummyTaskConnection(TaskConnectionBase):
    def __init__(self, duration=None):
        super().__init__()
        self.duration = duration
        self.running = False

    async def _run(self, started):
        self.running = True
        started()
        try:
            if self.duration is not None:
                await sleep(self.duration)
            else:
                await sleep_forever()
        finally:
            self.running = False


async def test_task_open_close(nursery, autojump_clock):
    conn = DummyTaskConnection()

    assert conn.is_disconnected
    assert not conn.running

    with raises(RuntimeError, match="assign a nursery"):
        await conn.open()

    conn.assign_nursery(nursery)
    await conn.open()

    assert conn.is_connected
    assert conn.running

    await sleep(1)
    await conn.close()

    assert conn.is_disconnected
    assert not conn.running


async def test_task_open_close_finite_duration(nursery, autojump_clock):
    conn = DummyTaskConnection(duration=10)

    assert conn.is_disconnected
    assert not conn.running

    with raises(RuntimeError, match="assign a nursery"):
        await conn.open()

    conn.assign_nursery(nursery)
    await conn.open()

    assert conn.is_connected
    assert conn.running

    await conn.wait_until_disconnected()

    assert conn.is_disconnected
    assert not conn.running
