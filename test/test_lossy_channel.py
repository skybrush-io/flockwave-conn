import pytest

from itertools import cycle
from trio import open_memory_channel

from flockwave.channels import create_lossy_channel


@pytest.fixture
def fake_rng():
    it = cycle([0.2, 0.2, 0.5, 0])
    return lambda: next(it)


async def consumer(queue, result):
    async with queue:
        async for item in queue:
            result.append(item)


async def test_lossy_receive(nursery, fake_rng):
    tx, rx = open_memory_channel(0)
    lossy_rx = create_lossy_channel(rx, random=fake_rng)

    async with tx:
        items = []
        nursery.start_soon(consumer, lossy_rx, items)
        for value in range(8):
            await tx.send(value)

    assert items == [0, 1, 2, 4, 5, 6]


async def test_lossy_receive_larger_prob(nursery, fake_rng):
    tx, rx = open_memory_channel(0)
    lossy_rx = create_lossy_channel(rx, random=fake_rng, loss_probability=0.3)

    async with tx:
        items = []
        nursery.start_soon(consumer, lossy_rx, items)
        for value in range(8):
            await tx.send(value)

    assert items == [2, 6]


async def test_lossy_send(nursery, fake_rng):
    tx, rx = open_memory_channel(0)
    lossy_tx = create_lossy_channel(tx, random=fake_rng)

    async with lossy_tx:
        items = []
        nursery.start_soon(consumer, rx, items)
        for value in range(8):
            await lossy_tx.send(value)

    assert items == [0, 1, 2, 4, 5, 6]


async def test_lossy_send_larger_prob(nursery, fake_rng):
    tx, rx = open_memory_channel(0)
    lossy_tx = create_lossy_channel(tx, random=fake_rng, loss_probability=0.3)

    async with lossy_tx:
        items = []
        nursery.start_soon(consumer, rx, items)
        for value in range(8):
            await lossy_tx.send(value)

    assert items == [2, 6]
