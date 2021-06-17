"""Concurrency-related utility functions."""

from contextlib import asynccontextmanager
from functools import partial, wraps
from inspect import iscoroutine, iscoroutinefunction
from trio import (
    Cancelled,
    CancelScope,
    Event,
    Lock,
    open_nursery,
    Nursery,
    WouldBlock,
    sleep,
)
from trio_util import RepeatedEvent
from typing import (
    Any,
    AsyncGenerator,
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    Generic,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Set,
    Union,
    Tuple,
    TypeVar,
)

__all__ = ("AsyncBundler", "aclosing", "cancellable", "Future", "FutureCancelled")


T = TypeVar("T")
T2 = TypeVar("T2")


class aclosing:
    """Context manager that closes an async generator when the context is
    exited. Similar to `closing()` in `contextlib`.
    """

    def __init__(self, aiter):
        self._aiter = aiter

    async def __aenter__(self):
        return self._aiter

    async def __aexit__(self, *args):
        await self._aiter.aclose()


def cancellable(func):
    """Decorator that extends an async function with an extra `cancel_scope`
    keyword argument and makes the function enter the cancel scope.
    """

    @wraps(func)
    async def decorated(*args, cancel_scope, **kwds):
        with cancel_scope:
            return await func(*args, **kwds)

    decorated._cancellable = True

    return decorated


def _identity(obj: Any) -> Any:
    """Identity function that returns its input argument."""
    return obj


def delayed(
    seconds: float,
    fn: Optional[Union[Callable[..., T], Callable[..., Awaitable[T]]]] = None,
    *,
    ensure_async: bool = False
) -> Union[Callable[..., T], Callable[..., Awaitable[T]]]:
    """Decorator or decorator factory that delays the execution of a
    synchronous function, coroutine or coroutine-returning function with a
    given number of seconds.

    Parameters:
        seconds: the number of seconds to delay with. Negative numbers will
            throw an exception. Zero will return the identity function.
        fn: the function, coroutine or coroutine-returning function to delay
        ensure_async: when set to `True`, synchronous functions will automatically
            be converted to asynchronous before delaying them. This is needed
            if the delayed function is going to be executed in the async
            event loop because a synchronous function that sleeps will block
            the entire event loop.

    Returns:
        the delayed function, coroutine or coroutine-returning function
    """
    if seconds < 0:
        raise ValueError("delay must not be negative")

    if seconds == 0 and not ensure_async:
        return _identity if fn is None else fn

    if fn is None:
        return partial(delayed, seconds, ensure_async=ensure_async)

    if iscoroutinefunction(fn):

        @wraps(fn)
        async def decorated(*args, **kwds):
            await sleep(seconds)
            return await fn(*args, **kwds)

    elif iscoroutine(fn):

        async def decorated():
            await sleep(seconds)
            return fn

        decorated = decorated()

    elif ensure_async:

        async def decorated(*args, **kwds):
            await sleep(seconds)
            return fn(*args, **kwds)

    else:

        def decorated(*args, **kwds):
            sleep(seconds)
            return fn(*args, **kwds)

    return decorated


class AsyncBundler(Generic[T]):
    """Asynchronous object that holds a bundle and supports the following
    operations:

    - Adding one or more items to the bundle

    - Waiting for the bundle to become non-empty and then removing all items
      from the bundle in one operation.

    This object is typically used in a producer-consumer setting. Producers
    add items to the bundle either one by one (with `add()`) or in batches
    (with `add_many()`). At the same time, a single consumer iterates over
    the bundle asynchronously and takes all items from it in each iteration.
    """

    _data: Set[T]
    _event: RepeatedEvent
    _lock: Lock

    def __init__(self):
        """Constructor."""
        self._data = set()
        self._event = RepeatedEvent()
        self._lock = Lock()

    def add(self, item: T) -> None:
        """Adds a single item to the bundle.

        Parameters:
            item: the item to add
        """
        self._data.add(item)
        self._event.set()

    def add_many(self, items: Iterable[T]) -> None:
        """Adds multiple items to the bundle from an iterable.

        Parameters:
            items: the items to add
        """
        self._data.update(items)
        if self._data:
            self._event.set()

    def clear(self) -> None:
        """Clears all the items currently waiting in the bundle."""
        self._data.clear()

    @asynccontextmanager
    async def iter(self) -> AsyncIterator[AsyncGenerator[Set[T], None]]:
        it = self.__aiter__()
        try:
            yield it
        finally:
            await it.aclose()

    async def __aiter__(self) -> AsyncGenerator[Set[T], None]:
        """Asynchronously iterates over non-empty batches of items that
        were added to the set.
        """
        it = None
        try:
            if self._lock.locked():
                raise RuntimeError("AsyncBundler can only have one listener")

            async with self._lock:
                it = self._event.events(repeat_last=True)
                async for _ in it:
                    result = set(self._data)
                    self._data.clear()
                    if result:
                        yield result
        finally:
            if it:
                await it.aclose()


class CancellableTaskGroup:
    """Object representing a group of tasks running in an associated nursery
    that can be cancelled with a single method call.
    """

    def __init__(self, nursery: Nursery):
        """Constructor.

        Parameters:
            nursery: the nursery that the tasks of the task group will be
                executed in.
        """
        self._nursery = nursery
        self._cancel_scopes = []

    def cancel_all(self) -> None:
        """Cancels all tasks running in the task group."""
        for cancel_scope in self._cancel_scopes:
            cancel_scope.cancel()
        del self._cancel_scopes[:]

    def start_soon(self, func, *args):
        """Starts a new task in the task group."""
        cancel_scope = CancelScope()
        self._cancel_scopes.append(cancel_scope)
        self._nursery.start_soon(partial(cancellable(func), cancel_scope=cancel_scope))


class FutureCancelled(RuntimeError):
    """Exception raised when trying to retrieve the result of a cancelled
    future.

    Note that it is fundamentally different from a Trio Cancelled_ error so
    it deserves its own exception class. For instance, calling
    `await future.wait()` raises Cancelled_ if the await operation itself
    was cancelled, but it raises FutureCancelled_ if the await operation
    finished but the future itself was cancelled in some other task.
    """

    pass


class Future(Generic[T]):
    """Object representing the result of a computation that is to be completed
    later.

    This object is essentially a Trio Event_ with an associated value. A Trio
    task may await on the result of the future while another one performs the
    computation and sets the value of the future when the computation is
    complete.
    """

    _cancelled: bool
    _error: Optional[Exception]
    _event: Event
    _value: Optional[T]

    def __init__(self):
        self._event = Event()
        self._cancelled = False
        self._value = None
        self._error = None

    def cancel(self) -> bool:
        """Cancels the future.

        Returns:
            `True` if the future was _cancelled_, `False` if the future is
            already _done_ or _cancelled_.
        """
        if self._event.is_set():
            return False

        self._cancelled = True
        self._event.set()

        return True

    async def call(self, func: Callable[..., Awaitable[T]], *args, **kwds) -> None:
        """Calls the given function, waits for its result and sets the result
        in the future.

        If the function throws an exception, sets the exception in the future.

        It must be ensured that you call this function only once; if it is called
        a second time while the execution of the first function is still in
        progress, it will apparently succeed, but then later on you will get an
        error when the second function terminates and it tries to write its
        result into the future.
        """
        self._ensure_not_done()
        try:
            self.set_result(await func(*args, **kwds))
        except Cancelled:
            self.cancel()
            raise
        except Exception as ex:
            self.set_exception(ex)

    def cancelled(self) -> bool:
        """Returns whether the future is done."""
        return self._cancelled

    def done(self) -> bool:
        """Returns whether the future is done."""
        return self._event.is_set()

    def exception(self) -> Exception:
        """Returns the exception that was set on this future.

        The exception (or `None` if no exception was set) is returned only if
        the future is _done_.

        Raises:
            FutureCancelled: if the future was cancelled
            WouldBlock: if the result of the future is not yet available
        """
        self._check_done_or_cancelled()
        return self._error  # type: ignore

    def result(self) -> T:
        """Returns the result of the future.

        If the future is _done_ and has a result set by the `set_result()` method,
        the result value is returned.

        If the future is _done_ and has an exception set by the `set_exception()`
        method, this method raises the exception.

        Raises:
            FutureCancelled: if the future was cancelled
            WouldBlock: if the result of the future is not yet available
        """
        self._check_done_or_cancelled()
        if self._error:
            raise self._error
        else:
            return self._value  # type: ignore

    def set_exception(self, exception: Exception) -> None:
        """Marks the future as _done_ and sets an exception.

        Raises:
            RuntimeError: if the future is already done
        """
        self._ensure_not_done()
        self._error = exception
        self._event.set()

    def set_result(self, value: T) -> None:
        """Marks the future as _done_ and sets its result.

        Raises:
            RuntimeError: if the future is already done
        """
        self._ensure_not_done()
        self._value = value
        self._event.set()

    async def wait(self) -> T:
        """Waits until the future is resolved, and then returns the value
        assigned to the future.

        If the execution behind the future yielded an exception, raises the
        exception itself.

        Returns:
            the value of the future

        Raises:
            FutureCancelled: if the future was cancelled
        """
        await self._event.wait()
        return self.result()

    def _check_done_or_cancelled(self) -> None:
        if not self._event.is_set():
            raise WouldBlock()

        if self._cancelled:
            raise FutureCancelled()

    def _ensure_not_done(self) -> None:
        if self._event.is_set():
            raise RuntimeError("future is already done")


class _FutureMapContext(Generic[T]):
    def __init__(self, future: Future[T], disposer: Callable[[], None]):
        self._disposer = disposer
        self._future = future

    async def __aenter__(self):
        return self._future

    async def __aexit__(self, exc_type, exc_value, tb):
        self._disposer()
        if exc_type is None:
            await self._future.wait()


class FutureMap(Mapping[str, Future[T]]):
    """Dictionary that maps arbitrary string keys to futures that are resolved
    to concrete values at a later time.

    You may not add new futures to the map directly; you need to use the
    `new()` method to add a new future. The method is a context manager; the
    future is kept in the map as long as the execution is inside the context.
    Also, the context will block upon exiting if the future is not done yet,
    and remove the future from the map after exiting the context.

    The typical use-case of this map is as follows:

    ```
    map = FutureMap()
    with map.new("some_id") as future:
        # pass the future to some other, already running task that will
        # eventually resolve it
        result = await future
        # do something with the result
    ```
    """

    _factory: Callable[[], Future[T]]
    _futures: Dict[str, Future[T]]

    def __init__(self, factory: Callable[[], Future[T]] = Future[T]):
        """Constructor.

        Parameters:
            factory: callable that can be used to create a new Future_ when
                invoked with no arguments
        """
        self._factory = factory
        self._futures = {}

    def __getitem__(self, key) -> Future[T]:
        return self._futures[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._futures)

    def __len__(self) -> int:
        return len(self._futures)

    def _dispose_future(self, id: str, future: Future[T]) -> None:
        if not future.done():
            future.cancel()

        existing_future = self._futures.get(id)
        if existing_future is future:
            del self._futures[id]

    def new(self, id: str, strict: bool = False) -> _FutureMapContext[T]:
        old_future = self._futures.get(id)

        if old_future:
            if strict:
                raise RuntimeError("Another operation is already in progress")
            else:
                self._dispose_future(id, old_future)

        self._futures[id] = future = self._factory()
        return _FutureMapContext(future, partial(self._dispose_future, id, future))


async def race(funcs: Dict[str, Callable[[], T]]) -> Tuple[str, T]:
    """Run multiple async functions concurrently and wait for at least one of
    them to complete. Return the key corresponding to the function and the
    result of the function as well.
    """
    holder: List[Tuple[str, T]] = []

    async with open_nursery() as nursery:
        cancel = nursery.cancel_scope.cancel
        for key, func in funcs.items():
            set_result = partial(_cancel_and_set_result, cancel, holder, key)
            nursery.start_soon(_wait_and_call, func, set_result)

    return holder[0]


def _cancel_and_set_result(
    cancel: Callable[[], None], holder: List[Tuple[str, T]], key: str, value: T
) -> None:
    holder.append((key, value))
    cancel()


async def _wait_and_call(f1: Callable[[], Awaitable[T]], f2: Callable[[T], T2]) -> T2:
    """Call an async function f1() and wait for its result. Call synchronous
    function `f2()` with the result of `f1()` when `f1()` returns.

    Returns:
        the return value of f2
    """
    result = await f1()
    return f2(result)
