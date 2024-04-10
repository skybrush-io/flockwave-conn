"""Helper functions to simulate packet loss on an existing Channel object,
mostly for debugging purposes.
"""

from random import random as random_01
from trio.abc import Channel
from typing import Callable

from .types import MessageType

__all__ = ("create_lossy_channel",)


def create_lossy_channel(
    channel: Channel[MessageType],
    loss_probability: float = 0.1,
    random: Callable[[], float] = random_01,
) -> Channel[MessageType]:
    """Takes a Trio-style channel object and creates another one that operates
    the same way but randomly loses received and sent messages with the
    given loss probability.

    Parameters:
        channel: the channel to wrap
        loss_probability: the probability of losing a message. Defaults to a
            moderate 10% packet loss.
        random: function to generate random numbers; must return a float
            between 0 (inclusive) and 1 (exclusive)
    """
    return LossyChannelWrapper(channel, loss_probability, random=random)


class LossyChannelWrapper(Channel[MessageType]):
    """Implementation of a lossy Trio-style channel that randomly loses received
    and sent messages with a given loss probability.
    """

    def __init__(
        self,
        channel: Channel[MessageType],
        loss_probability: float = 0.1,
        *,
        random: Callable[[], float] = random_01,
    ):
        """Constructor.

        Parameters:
            channel: the channel to wrap
            loss_probability: the probability of losing a message. Defaults to a
                moderate 10% packet loss.
            random: function to generate random numbers; must return a float
                between 0 (inclusive) and 1 (exclusive)
        """
        self._wrapped = channel
        self._loss_probability = float(loss_probability)
        self._random = random

    def __getattr__(self, name: str):
        return getattr(self._wrapped, name)

    async def aclose(self) -> None:
        await self._wrapped.aclose()

    async def send(self, value: MessageType) -> None:
        if self._random() >= self._loss_probability:
            await self._wrapped.send(value)

    async def receive(self) -> MessageType:
        while True:
            message = await self._wrapped.receive()
            if self._random() >= self._loss_probability:
                return message
