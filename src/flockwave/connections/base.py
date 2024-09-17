"""Base connection classes."""

import logging
import os

from abc import ABCMeta, abstractmethod, abstractproperty
from blinker import Signal
from enum import Enum
from functools import partial
from trio import CancelScope, Event, Nursery, TASK_STATUS_IGNORED, wrap_file
from trio_util import AsyncBool
from typing import Any, Callable, Generic, Optional, Protocol, TypeVar


__all__ = (
    "BroadcastConnection",
    "Connection",
    "ConnectionState",
    "ConnectionBase",
    "FDConnectionBase",
    "ListenerConnection",
    "ReadableConnection",
    "RWConnection",
    "TaskConnectionBase",
    "WritableConnection",
)


class ConnectionState(Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DISCONNECTING = "DISCONNECTING"

    @property
    def is_transitioning(self) -> bool:
        return self in (ConnectionState.CONNECTING, ConnectionState.DISCONNECTING)


log = logging.getLogger(__name__.rpartition(".")[0])


class Connection(metaclass=ABCMeta):
    """Interface specification for stateful connection objects."""

    connected = Signal(doc="Signal sent after the connection was established.")
    disconnected = Signal(doc="Signal sent after the connection was torn down.")
    state_changed = Signal(
        doc="""\
        Signal sent whenever the state of the connection changes.

        Parameters:
            new_state: the new state
            old_state: the old state
        """
    )

    @abstractmethod
    async def open(self) -> None:
        """Opens the connection. No-op if the connection is open already."""
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        """Closes the connection. No-op if the connection is closed already."""
        raise NotImplementedError

    @property
    def is_disconnected(self) -> bool:
        """Returns whether the connection is disconnected (and not connecting and
        not disconnecting)."""
        return self.state is ConnectionState.DISCONNECTED

    @property
    def is_connected(self) -> bool:
        """Returns whether the connection is connected."""
        return self.state is ConnectionState.CONNECTED

    @property
    def is_transitioning(self) -> bool:
        """Returns whether connection is currently transitioning."""
        return self.state.is_transitioning

    @abstractproperty
    def state(self) -> ConnectionState:
        """Returns the state of the connection; one of the constants from
        the ``ConnectionState`` enum.
        """
        raise NotImplementedError

    @abstractmethod
    async def wait_until_connected(self) -> None:
        """Blocks the current task until the connection becomes connected.
        Returns immediately if the connection is already connected.
        """
        raise NotImplementedError

    @abstractmethod
    async def wait_until_disconnected(self) -> None:
        """Blocks the current task until the connection becomes disconnected.
        Returns immediately if the connection is already disconnected.
        """
        raise NotImplementedError

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()


T = TypeVar("T")
RT = TypeVar("RT")
WT = TypeVar("WT")


class ListenerConnection(Connection, Generic[T]):
    """Interface specification for connection objects that wait for (i.e.
    listen to) new connections and then spawn new tasks for every new
    connection attempt.
    """

    @abstractmethod
    async def accept(self) -> T:
        """Waits for the next incoming connection and returns an object
        representing the connection when it arrives.
        """
        raise NotImplementedError


class ReadableConnection(Connection, Generic[T]):
    """Interface specification for connection objects that we can read data from."""

    @abstractmethod
    async def read(self) -> T:
        """Reads some data from the connection.

        Returns:
            the data that was read
        """
        raise NotImplementedError


class WritableConnection(Connection, Generic[T]):
    """Interface specification for connection objects that we can write data to."""

    @abstractmethod
    async def write(self, data: T) -> None:
        """Writes the given data to the connection.

        Parameters:
            data: the data to write
        """
        raise NotImplementedError


class RWConnection(ReadableConnection[RT], WritableConnection[WT]):
    """Interface specification for connection objects that we can read from and
    write data to.

    This type is mostly present for type checking purposes.
    """

    pass


class BroadcastConnection(Connection, Generic[T]):
    """Interface specification for connection objects that support
    broadcasting.
    """

    @abstractmethod
    async def broadcast(self, data: T):
        """Broadcasts the given data on the connection.

        Parameters:
            data: the data to write
        """
        raise NotImplementedError


class BroadcastAddressOverride(Generic[T]):
    """Interface specification for connection objects that support
    overriding their broadcast address.
    """

    def clear_user_defined_broadcast_address(self) -> None:
        """Clears the user-defined broadcast address of the connection,
        returning it to a state where the broadcast address is the default one.
        """
        self.set_user_defined_broadcast_address(None)

    @abstractmethod
    def set_user_defined_broadcast_address(self, address: Optional[T]) -> None:
        """Sets the user-defined broadcast address of the connection.

        User-defined broadcast address take precedence over the default
        broadcast address of the connection.

        Args:
            address: the address to set. Setting the address to ``None`` disables
                the user-defined address and returns to the default
                broadcast address of the connection.
        """
        raise NotImplementedError


class ConnectionBase(Connection):
    """Base class for stateful connection objects.

    Connection objects may be in one of the following four states:

        - ``DISCONNECTED``: the connection is down

        - ``CONNECTING``: the connection is being established

        - ``CONNECTED``: the connection is up

        - ``DISCONNECTING``: the connection is being closed

    Each connection object provides three signals that interested parties
    may connect to if they want to be notified about changes in the connection
    states: ``state_changed``, ``connected`` and ``disconnected``.
    ``state_changed`` is fired whenever the connection state changes.
    ``connected`` is fired when the connection enters the ``CONNECTED`` state
    from any other state. ``disconnected`` is fired when the connection enters
    the ``DISCONNECTED`` state from any other state.

    Classes derived from this base class *MUST NOT* set the ``_state`` variable
    directly; they *MUST* use the ``_set_state`` method instead to ensure that
    the signals are dispatched appropriately.
    """

    def __init__(self):
        """Constructor."""
        self._state: ConnectionState = ConnectionState.DISCONNECTED

        self._is_connected = AsyncBool(False)  # type: ignore
        self._is_disconnected = AsyncBool(True)  # type: ignore

    @property
    def state(self) -> ConnectionState:
        """The state of the connection."""
        return self._state

    def _set_state(self, new_state: ConnectionState) -> None:
        """Sets the state of the connection to a new value and sends the
        appropriate signals.
        """
        old_state = self._state
        if new_state == old_state:
            return

        self._state = new_state

        self.state_changed.send(self, old_state=old_state, new_state=new_state)

        if not self._is_connected.value and new_state is ConnectionState.CONNECTED:
            self._is_connected.value = True
            self.connected.send(self)

        if (
            not self._is_disconnected.value
            and new_state is ConnectionState.DISCONNECTED
        ):
            self._is_disconnected.value = True
            self.disconnected.send(self)

        if self._is_connected.value and new_state is not ConnectionState.CONNECTED:
            self._is_connected.value = False

        if (
            self._is_disconnected.value
            and new_state is not ConnectionState.DISCONNECTED
        ):
            self._is_disconnected.value = False

    async def close(self) -> None:
        """Base implementation of Connection.close() that manages the state of
        the connection correctly.

        Typically, you don't need to override this method in subclasses;
        override `_close()` instead.
        """
        if self.state is ConnectionState.DISCONNECTED:
            return
        elif self.state is ConnectionState.DISCONNECTING:
            return await self.wait_until_disconnected()
        elif self.state is ConnectionState.CONNECTING:
            await self.wait_until_connected()

        self._set_state(ConnectionState.DISCONNECTING)
        success = False
        try:
            # TODO(ntamas): use a timeout here!
            await self._close()
            success = True
        finally:
            self._set_state(
                ConnectionState.DISCONNECTED if success else ConnectionState.CONNECTED
            )

    async def open(self) -> None:
        """Base implementation of Connection.open() that manages the state
        of the connection correctly.

        Typically, you don't need to override this method in subclasses;
        override `_open()` instead.
        """
        if self.state is ConnectionState.CONNECTED:
            return
        elif self.state is ConnectionState.CONNECTING:
            return await self.wait_until_connected()
        elif self.state is ConnectionState.DISCONNECTING:
            await self.wait_until_disconnected()

        self._set_state(ConnectionState.CONNECTING)
        success = False
        try:
            # TODO(ntamas): use a timeout here!
            await self._open()
            success = True
        finally:
            self._set_state(
                ConnectionState.CONNECTED if success else ConnectionState.DISCONNECTED
            )

    async def wait_until_connected(self) -> None:
        """Blocks the execution until the connection becomes connected."""
        await self._is_connected.wait_value(True)

    async def wait_until_disconnected(self) -> None:
        """Blocks the execution until the connection becomes disconnected."""
        await self._is_disconnected.wait_value(True)

    @abstractmethod
    async def _open(self) -> None:
        """Internal implementation of `ConnectionBase.open()`.

        Override this method in subclasses to implement how your connection
        is opened. No need to update the state variable from inside this
        method; the caller will do it automatically.

        Make sure that the implementation of this function does not block the
        main event loop. Use a worker thread if needed.
        """
        raise NotImplementedError

    @abstractmethod
    async def _close(self) -> None:
        """Internal implementation of `ConnectionBase.close()`.

        Override this method in subclasses to implement how your connection
        is closed. No need to update the state variable from inside this
        method; the caller will do it automatically.

        Make sure that the implementation of this function does not block the
        main event loop. Use a worker thread if needed.
        """
        raise NotImplementedError


class AsyncFileLike(Protocol):
    """Interface specification for asynchronous file-like objects that can be
    used in conjunction with FDConnectionBase_.
    """

    async def flush(self) -> None: ...
    async def read(self, size: int = -1) -> bytes: ...
    async def write(self, data: bytes) -> None: ...


class FDConnectionBase(ConnectionBase, RWConnection[bytes, bytes], metaclass=ABCMeta):
    """Base class for connection objects that have an underlying numeric
    file handle or file-like object.
    """

    file_handle_changed = Signal(
        doc="""\
        Signal sent whenever the file handle associated to the connection
        changes.

        Parameters:
            new_handle (int): the new file handle
            old_handle (int): the old file handle
        """
    )

    _file_handle: Optional[int] = None
    """The file handle associated to the connection."""

    _file_handle_owned: bool = False
    """Specifies whether the file handle is owned by this connection and should
    be closed when the connection is closed.
    """

    _file_object: Optional[AsyncFileLike] = None
    """The file-like object associated to the connection."""

    autoflush: bool = False
    """Whether to flush the file handle automatically after each write."""

    def __init__(self, autoflush: bool = False):
        """Constructor."""
        super().__init__()
        self.autoflush = bool(autoflush)

    def fileno(self) -> Optional[int]:
        """Returns the underlying file handle of the connection, for sake of
        compatibility with other file-like objects in Python. Returns `None`
        if the connection is not open.
        """
        return self._file_handle

    async def flush(self) -> None:
        """Flushes the data recently written to the connection."""
        if self._file_object is not None:
            await self._file_object.flush()

    @property
    def fd(self) -> Optional[int]:
        """Returns the underlying file handle of the connection. Returns `None`
        if the connection is not open.
        """
        return self._file_handle

    @property
    def fp(self):
        """Returns the underlying file-like object of the connection."""
        return self._file_object

    async def _close(self) -> None:
        """Closes the file connection."""
        assert self._file_object is not None
        self._detach()

    async def _open(self) -> None:
        """Opens the file connection."""
        obj = await self._get_file_object_during_open()
        if obj is not None:
            self._attach(obj)
        else:
            raise RuntimeError("No file object was returned during open()")

    def _attach(self, handle_or_object: Any) -> None:
        """Associates a file handle or file-like object to the connection.
        This is the method that derived classes should use whenever the
        connection is associated to a new file handle or file-like object.
        """
        if handle_or_object is None:
            handle, obj, handle_owned = None, None, False
        elif isinstance(handle_or_object, int):
            handle, obj, handle_owned = (
                handle_or_object,
                os.fdopen(handle_or_object),
                False,
            )
        else:
            handle, obj, handle_owned = (
                handle_or_object.fileno(),
                handle_or_object,
                True,
            )

        # Wrap the raw sync file handle in Trio's async file handle
        if obj is not None and not hasattr(obj, "aclose"):
            obj = wrap_file(obj)

        old_handle = self._file_handle
        self._set_file_handle(handle)
        self._set_file_object(obj)
        self._file_handle_owned = handle_owned

        if old_handle != self._file_handle:
            self.file_handle_changed.send(
                self, old_handle=old_handle, new_handle=self._file_handle
            )

    def _detach(self) -> None:
        """Detaches the connection from its current associated file handle
        or file-like object.
        """
        self._attach(None)

    @abstractmethod
    async def _get_file_object_during_open(self) -> Any:
        """Implementation of the core of the ``open()`` method; must return
        a file handle or object that the connection will be attached to.
        Returning ``None`` will close the connection immediately.
        """
        raise NotImplementedError

    def _set_file_handle(self, value):
        """Setter for the ``_file_handle`` property. Derived classes should
        not set ``_file_handle`` or ``_file_object`` directly; they should
        use ``_attach()`` or ``_detach()`` instead.

        Parameters:
            value (int): the new file handle

        Returns:
            bool: whether the file handle has changed
        """
        if self._file_handle == value:
            return False

        self._file_handle = value
        return True

    def _set_file_object(self, value) -> bool:
        """Setter for the ``_file_object`` property. Derived classes should
        not set ``_file_handle`` or ``_file_object`` directly; they should
        use ``_attach()`` or ``_detach()`` instead.

        Parameters:
            value: the new file object or ``None`` if the connection is not
                associated to a file-like object (which may happen even if there
                is a file handle if the file handle does not have a file-like
                object representation)

        Returns:
            bool: whether the file object has changed
        """
        if self._file_object == value:
            return False

        self._file_object = value
        return True

    async def read(self, size: int = -1) -> bytes:
        """Reads the given number of bytes from the connection.

        Parameters:
            size: the number of bytes to read; -1 means to read all available
                data

        Returns:
            the data that was read, or an empty bytes object if the end of file
            was reached
        """
        assert self._file_object is not None
        return await self._file_object.read(size)

    async def write(self, data: bytes) -> None:
        """Writes the given data to the connection.

        Parameters:
            data: the data to write
        """
        assert self._file_object is not None
        await self._file_object.write(data)
        if self.autoflush:
            await self.flush()


class TaskConnectionBase(ConnectionBase):
    """Connection subclass that implements the opening and closing of a
    connection in a single asynchronous task; the connection is considered open
    when the task started and it is considered closed when the task stopped for
    any reason.

    Instances of this class require a nursery that will supervise the execution
    of the task. This means that you need to call `assign_nursery()` before
    opening the connection. You can assign a nursery to a connection only when
    it is closed.
    """

    _closed_event: Optional[Event]

    def assign_nursery(self, nursery: Nursery) -> None:
        """Assigns a nursery to the connection that will be responsible for
        executing the task.
        """
        if self.state != ConnectionState.DISCONNECTED:
            raise RuntimeError(
                "You can assign a nursery only when the connection is closed"
            )

        self._nursery = nursery
        self._cancel_scope = None
        self._closed_event = None

    async def _open(self) -> None:
        if not hasattr(self, "_nursery"):
            raise RuntimeError("You need to assign a nursery to the connection first")

        self._closed_event = Event()
        self._cancel_scope = await self._nursery.start(
            self._create_cancel_scope_and_run
        )

    async def _close(self) -> None:
        if self._cancel_scope:
            scope = self._cancel_scope
            self._cancel_scope = None
            scope.cancel()
            if self._closed_event is not None:
                await self._closed_event.wait()

    async def _create_cancel_scope_and_run(
        self, *, task_status=TASK_STATUS_IGNORED
    ) -> None:
        """Creates a cancel scope that can be used by the ``_close()`` method
        to cancel the task, and then runs the task of the connection by calling
        the ``_run()`` method.
        """
        with CancelScope() as scope:
            started = partial(task_status.started, scope)
            try:
                await self._run(started=started)
            finally:
                if self._closed_event is not None:
                    self._closed_event.set()

        await self.close()

    @abstractmethod
    async def _run(self, started: Callable[[], None]) -> None:
        """Runs the main task of the connection.

        Must be overridden in subclasses. The implementation must ensure that
        the given `started()` callable is called when the task is ready for
        execution.
        """
        raise NotImplementedError
