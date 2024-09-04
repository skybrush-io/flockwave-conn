from __future__ import annotations

from typing import Protocol, TypedDict, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    from .base import Connection

__all__ = ("Capabilities", "CapabilitySupport", "get_connection_capabilities")


class Capabilities(TypedDict):
    """Typed dictionary that contains information about the capabilities of a
    connection.
    """

    can_broadcast: bool
    """Stores whether the connection can send broadcast packets."""

    can_receive: bool
    """Stores whether the connection can receive data."""

    can_send: bool
    """Stores whether the connection can send data."""


@runtime_checkable
class CapabilitySupport(Protocol):
    """Interface specification for class-level properties that must be present
    on a Connection_ object to provide _overridden_ information about the
    capabilities of the connection.

    In the absence of the method described in this protocol, the capabilities
    of the connection will be inferred from its inheritance hierarchy.
    """

    def _get_capabilities(self) -> Capabilities:
        """Returns the capabilities of a connection.

        Capabilities are not expected to change during the lifetime of a
        connection.
        """
        ...


def get_connection_capabilities(conn: Connection) -> Capabilities:
    """Returns the capabilities of the given connection.

    Args:
        conn: the connection whose capabilities are queried
    """
    from .base import BroadcastConnection, ReadableConnection, WritableConnection

    if isinstance(conn, CapabilitySupport):
        return conn._get_capabilities()
    else:
        return {
            "can_broadcast": isinstance(conn, BroadcastConnection),
            "can_receive": isinstance(conn, ReadableConnection),
            "can_send": isinstance(conn, WritableConnection),
        }
