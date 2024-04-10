"""Base listener classes."""

import logging

from abc import ABCMeta, abstractmethod, abstractproperty
from blinker import Signal
from enum import Enum
from trio import CancelScope, Event, Nursery, TASK_STATUS_IGNORED
from trio.abc import Stream
from trio_util import AsyncBool
from typing import Callable, Optional


__all__ = ("Listener", "ListenerState", "ListenerBase")


class ListenerState(Enum):
    CLOSED = "CLOSED"
    PREPARING = "PREPARING"
    OPEN = "OPEN"
    CLOSING = "CLOSING"

    @property
    def is_transitioning(self) -> bool:
        return self in (ListenerState.PREPARING, ListenerState.CLOSING)


log = logging.getLogger(__name__.rpartition(".")[0])


class Listener(metaclass=ABCMeta):
    """Interface specification for stateful listener objects."""

    opened = Signal(
        doc="Signal sent after the listener started listening for incoming connections."
    )
    closed = Signal(
        doc="Signal sent after the listener stopped listening for incoming connections."
    )
    state_changed = Signal(
        doc="""\
        Signal sent whenever the state of the listener changes.

        Parameters:
            new_state: the new state
            old_state: the old state
        """
    )

    @abstractmethod
    async def open(self) -> None:
        """Opens the listener. No-op if the listener is listening already."""
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        """Closes the listener. No-op if the listener is closed already."""
        raise NotImplementedError

    @property
    def is_closed(self) -> bool:
        """Returns whether the listener is closed (and not closing and
        not preparing)."""
        return self.state is ListenerState.CLOSED

    @property
    def is_open(self) -> bool:
        """Returns whether the connection is open."""
        return self.state is ListenerState.OPEN

    @property
    def is_transitioning(self) -> bool:
        """Returns whether listener is currently transitioning."""
        return self.state.is_transitioning

    @abstractproperty
    def state(self) -> ListenerState:
        """Returns the state of the listener; one of the constants from
        the ``ConnectionState`` enum.
        """
        raise NotImplementedError

    @abstractmethod
    async def wait_until_open(self) -> None:
        """Blocks the current task until the listener becomes open. Returns
        immediately if the listener is already open.
        """
        raise NotImplementedError

    @abstractmethod
    async def wait_until_closed(self) -> None:
        """Blocks the execution until the listener becomes closed. Return
        immediately if the connection is already disconnected.
        """
        raise NotImplementedError

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()


class ListenerBase(Listener):
    """Base class for stateful listener objects.

    Listener objects may be in one of the following four states:

        - ``CLOSED``: the listener is closed and not listening for incoming
          connections

        - ``PREPARING``: the listener is being prepared to accept connections

        - ``OPEN``: the listener is open and is actively listening for
          incoming connections

        - ``CLOSING``: the listener is being closed

    Each listener object provides three signals that interested parties
    may connect to if they want to be notified about changes in the listener
    states: ``state_changed``, ``open`` and ``closed``.
    ``state_changed`` is fired whenever the listener state changes.
    ``open`` is fired when the listener enters the ``OPEN`` state
    from any other state. ``closed`` is fired when the connection enters
    the ``CLOSED`` state from any other state.

    Classes derived from this base class *MUST NOT* set the ``_state`` variable
    directly; they *MUST* use the ``_set_state`` method instead to ensure that
    the signals are dispatched appropriately.
    """

    def __init__(self):
        """Constructor."""
        self._state = ListenerState.CLOSED

        self._is_open = AsyncBool(False)
        self._is_closed = AsyncBool(True)

    @property
    def state(self):
        """The state of the listener."""
        return self._state

    def _set_state(self, new_state):
        """Sets the state of the listener to a new value and sends the
        appropriate signals.
        """
        old_state = self._state
        if new_state == old_state:
            return

        self._state = new_state

        self.state_changed.send(self, old_state=old_state, new_state=new_state)

        if not self._is_open.value and new_state is ListenerState.OPEN:
            self._is_open.value = True
            self.opened.send(self)

        if not self._is_closed.value and new_state is ListenerState.CLOSED:
            self._is_closed.value = True
            self.closed.send(self)

        if self._is_open.value and new_state is not ListenerState.OPEN:
            self._is_open.value = False

        if self._is_closed.value and new_state is not ListenerState.CLOSED:
            self._is_closed.value = False

    async def close(self):
        """Base implementation of Listener.close() that manages the state of
        the connection correctly.

        Typically, you don't need to override this method in subclasses;
        override `_close()` instead.
        """
        if self.state is ListenerState.CLOSED:
            return
        elif self.state is ListenerState.CLOSING:
            return await self.wait_until_closed()
        elif self.state is ListenerState.PREPARING:
            await self.wait_until_open()

        self._set_state(ListenerState.CLOSING)
        success = False
        try:
            # TODO(ntamas): use a timeout here!
            await self._close()
            success = True
        finally:
            self._set_state(ListenerState.CLOSED if success else ListenerState.OPEN)

    async def open(self):
        """Base implementation of Listener.open() that manages the state
        of the connection correctly.

        Typically, you don't need to override this method in subclasses;
        override `_open()` instead.
        """
        if self.state is ListenerState.OPEN:
            return
        elif self.state is ListenerState.PREPARING:
            return await self.wait_until_open()
        elif self.state is ListenerState.CLOSING:
            await self.wait_until_closed()

        self._set_state(ListenerState.PREPARING)
        success = False
        try:
            # TODO(ntamas): use a timeout here!
            await self._open()
            success = True
        finally:
            self._set_state(ListenerState.OPEN if success else ListenerState.CLOSED)

    async def wait_until_open(self):
        """Blocks the execution until the listener becomes open."""
        await self._is_open.wait_value(True)

    async def wait_until_closed(self):
        """Blocks the execution until the listener becomes closed."""
        await self._is_closed.wait_value(True)

    @abstractmethod
    async def _open(self):
        """Internal implementation of `ListenerBase.open()`.

        Override this method in subclasses to implement how your listener
        is opened. No need to update the state variable from inside this
        method; the caller will do it automatically.
        """
        raise NotImplementedError

    @abstractmethod
    async def _close(self):
        """Internal implementation of `ListenerBase.close()`.

        Override this method in subclasses to implement how your listener
        is closed. No need to update the state variable from inside this
        method; the caller will do it automatically.
        """
        raise NotImplementedError


TrioConnectionHandler = Callable[[Stream], None]


class TrioListenerBase(ListenerBase):
    """Specialization of ListenerBase_ for Trio-style listeners.

    In Trio, the common pattern is that a listener can be opened by spawning
    a task with a dedicated function such as `serve_tcp()`. The listener
    listens for inbound connections in the task, and it can be closed by
    cancelling the task itself.

    Trio-style listeners need a Trio nursery that can be used to spawn a
    new task. The nursery has to be provided to the constructor of the listener,
    or, alternatively, after construction in the `nursery` property.

    In general, the owner of the nursery should not be worried about exceptions
    propagating out from the listener task; TrioListenerBase_ will handle these
    exceptions appropriately.
    """

    def __init__(
        self,
        *,
        handler: Optional[TrioConnectionHandler] = None,
        nursery: Optional[Nursery] = None,
    ):
        """Constructor.

        Parameters:
            handler: the handler function that will be called for every
                connection that was established
            nursery: the Trio nursery that will be the owner of the listener
                task spawned by this instance
        """
        super().__init__()

        self.nursery = nursery
        self.handler = handler

        self._cancel_scope = None
        self._task_exited = None

    async def _close(self):
        if self._cancel_scope:
            self._cancel_scope.cancel()
            self._cancel_scope = None

        await self._task_exited.wait()

    def _handle_exception(self, ex):
        """Handles an exception that happened while running the listener task.

        The default implementation logs the exception.
        """
        log.exception(ex)

    async def _open(self):
        if self.nursery is None:
            raise RuntimeError(
                "You must assign a nursery to a {!r} before opening it".format(
                    self.__class__
                )
            )

        await self.nursery.start(self._run_internal_trio_task)

    async def _run_internal_trio_task(self, *, task_status=TASK_STATUS_IGNORED):
        """Executes the internal, cancellable Trio task that listens for
        incoming connections.

        Do not override this method unless you know what you are doing.
        Subclasses should override the `_run()` method instead. This function
        sets up the cancellation scope for the internal task and catches
        exceptions raised from the task so you don't have to deal with these
        in `_run()`.
        """
        self._cancel_scope = CancelScope()
        self._task_exited = Event()

        with self._cancel_scope:
            try:
                await self._run(handler=self.handler, task_status=task_status)
            except Exception as ex:
                self._handle_exception(ex)

            # Task exited without it being cancelled; this means that the
            # listener must be closed explicitly.
            self.nursery.start_soon(self.close)

        self._cancel_scope = None
        self._task_exited.set()

    @abstractmethod
    async def _run(self, handler, task_status) -> None:
        """Executes the internal Trio task that listens for incoming
        connections.

        The listener is considered to be open while this task is running.
        When the task exits or is cancelled, the connection will be closed
        automatically.

        Parameters:
            handler: a connection handler that will be called by Trio for every
                connection that was established by the listener
            task_status: Trio task status argument. It is the responsibility
                of this method to call the `started()` method on this object
                to notify the listener instance that it is now open and
                accepting connections, or to arrange for someone else (e.g.,
                Trio's `serve_tcp()` or similar method) to call this method
                when needed. Failure to do so will mean that the listener is
                never considered as open.
        """
        raise NotImplementedError
