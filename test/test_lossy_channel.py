from itertools import cycle
from typing import TypeVar

import pytest
from trio import open_memory_channel
from trio.abc import Channel, ReceiveChannel, SendChannel

from flockwave.channels import create_lossy_channel


@pytest.fixture
def fake_rng():
    it = cycle([0.2, 0.2, 0.5, 0])
    return lambda: next(it)


T = TypeVar("T")


async def consumer(queue: ReceiveChannel[T], result: list[T]):
    async with queue:
        async for item in queue:
            result.append(item)


class MemoryChannel(Channel[T]):
    def __init__(self, capacity: int = 0):
        self._tx, self._rx = open_memory_channel[T](capacity)

    async def aclose(self) -> None:
        await self._tx.aclose()
        await self._rx.aclose()

    async def send(self, value: T) -> None:
        await self._tx.send(value)

    async def receive(self) -> T:
        return await self._rx.receive()

    @property
    def tx(self) -> SendChannel[T]:
        return self._tx

    @property
    def rx(self) -> ReceiveChannel[T]:
        return self._rx


async def test_lossy_receive(nursery, fake_rng):
    chan = MemoryChannel[int]()
    lossy_chan = create_lossy_channel(chan, random=fake_rng)

    async with chan.tx:
        items = []
        nursery.start_soon(consumer, lossy_chan, items)
        for value in range(8):
            await chan.tx.send(value)

    assert items == [0, 1, 2, 4, 5, 6]


async def test_lossy_receive_larger_prob(nursery, fake_rng):
    chan = MemoryChannel[int]()
    lossy_chan = create_lossy_channel(chan, random=fake_rng, loss_probability=0.3)

    async with chan.tx:
        items = []
        nursery.start_soon(consumer, lossy_chan, items)
        for value in range(8):
            await chan.tx.send(value)

    assert items == [2, 6]


async def test_lossy_send(nursery, fake_rng):
    chan = MemoryChannel[int]()
    lossy_chan = create_lossy_channel(chan, random=fake_rng)

    async with lossy_chan:
        items = []
        nursery.start_soon(consumer, chan.rx, items)
        for value in range(8):
            await lossy_chan.send(value)

    assert items == [0, 1, 2, 4, 5, 6]


async def test_lossy_send_larger_prob(nursery, fake_rng):
    chan = MemoryChannel[int]()
    lossy_chan = create_lossy_channel(chan, random=fake_rng, loss_probability=0.3)

    async with lossy_chan:
        items = []
        nursery.start_soon(consumer, chan.rx, items)
        for value in range(8):
            await lossy_chan.send(value)

    assert items == [2, 6]
