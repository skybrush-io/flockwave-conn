"""Dummy connection that does nothing."""

from trio import sleep

from .base import ConnectionBase
from .factory import create_connection


@create_connection.register("dummy")
class DummyConnection(ConnectionBase):
    """Dummy connection that does nothing and can be opened and closed any time
    without performing any IO.
    """

    async def _open(self):
        # Force a Trio checkpoint
        await sleep(0)

    async def _close(self):
        # Force a Trio checkpoint
        await sleep(0)
