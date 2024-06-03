from functools import partial
from typing import TYPE_CHECKING

from ..connections.factory import Factory

if TYPE_CHECKING:
    from .base import Listener


create_listener = Factory[Listener]()
"""Singleton listener factory."""


def create_listener_factory(*args, **kwds):
    """Creates a listener factory function that creates a listener
    configured in a specific way when invoked with no arguments.

    This is essentially a deferred call to `create_listener()`
    """
    return partial(create_listener, *args, **kwds)
