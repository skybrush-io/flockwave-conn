"""Dummy connection that does nothing."""

from trio import sleep, sleep_forever
from typing import Any

from .base import ConnectionBase, RWConnection
from .factory import create_connection


@create_connection.register("dummy")
class DummyConnection(ConnectionBase, RWConnection[bytes, Any]):
    """Dummy connection that does nothing and can be opened and closed any time
    without performing any IO.
    """

    async def _open(self) -> None:
        # Force a Trio checkpoint
        await sleep(0)

    async def _close(self) -> None:
        # Force a Trio checkpoint
        await sleep(0)

    async def read(self) -> bytes:
        await sleep_forever()
        return b""

    async def write(self, data: Any) -> None:
        pass
