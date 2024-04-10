"""Connection for a serial port."""

import platform
import re

from fnmatch import fnmatch
from os import dup
from trio import BusyResourceError, ClosedResourceError, sleep, to_thread
from trio.abc import Stream
from trio.lowlevel import wait_readable
from typing import Optional, Union

from .factory import create_connection
from .stream import StreamConnectionBase

__all__ = ("SerialPortConnection",)


class SerialPortStreamBase(Stream):
    """Base class for serial port stream implementations."""

    @classmethod
    async def create(cls, *args, **kwds) -> Stream:
        """Constructs a new `pySerial` serial port object, associates it to a
        SerialStream_ and returns the serial stream itself.

        All positional and keyword arguments are forwarded to the constructor
        of the Serial_ object from `pySerial`.

        Returns:
            the constructed serial stream
        """
        from serial import Serial

        return cls(Serial(timeout=0, *args, **kwds))  # type: ignore


class ConflictDetector:
    """Detect when two tasks are about to perform operations that would
    conflict.

    Use as a synchronous context manager; if two tasks enter it at the same
    time then the second one raises an error. You can use it when there are
    two pieces of code that *would* collide and need a lock if they ever were
    called at the same time, but that should never happen.

    This is copied straight from `trio._util`.
    """

    def __init__(self, msg):
        self._msg = msg
        self._held = False

    def __enter__(self):
        if self._held:
            raise BusyResourceError(self._msg)
        else:
            self._held = True

    def __exit__(self, *args):
        self._held = False


class _ThreadedSerialPortStream(SerialPortStreamBase):
    """A Trio stream implementation that talks to a serial port using
    PySerial in a separate thread. Used on Windows where we don't have
    FdStream in `trio`.
    """

    #: This matches the default from trio.lowlevel.FdStream
    DEFAULT_RECEIVE_SIZE = 65536

    def __init__(self, device):
        """Constructor.

        Do not use this method unless you know what you are doing; use
        `SerialPortStream.create()` instead.

        Parameters:
            device: the `pySerial` serial port object to manage in this stream.
                It must already be open.
        """
        self._device = device

        self._send_conflict_detector = ConflictDetector(
            "another task is using this stream for send"
        )
        self._receive_conflict_detector = ConflictDetector(
            "another task is using this stream for receive"
        )

        self._closing = False

    async def aclose(self) -> None:
        """Closes the serial port."""
        self._closing = True
        await to_thread.run_sync(self._device.close)

    async def receive_some(self, max_bytes: Optional[int] = None) -> bytes:
        if max_bytes is None:
            max_bytes = self.DEFAULT_RECEIVE_SIZE

        with self._receive_conflict_detector:
            while not self._closing:
                to_read = self._device.in_waiting
                if to_read:
                    return await to_thread.run_sync(
                        self._device.read, min(to_read, max_bytes)
                    )
                else:
                    # nothing to read at the moment, wait a bit
                    await sleep(0.01)

        raise ClosedResourceError()

    async def send_all(self, data: bytes):
        if not data:
            # make sure it's a checkpoint
            await sleep(0)
            return

        with self._send_conflict_detector:
            while data:
                num_written = await to_thread.run_sync(self._device.write, data)
                if num_written < 0:
                    raise RuntimeError("serial.write() returned a negative number")

                data = data[num_written:]

    async def wait_send_all_might_not_block(self) -> None:
        pass


class _FdStreamBasedSerialPortStream(SerialPortStreamBase):
    """A Trio stream implementation that talks to a serial port using
    PySerial in a separate thread. Used on all sensible platforms where
    we can leverage `trio.FdStream`.
    """

    def __init__(self, device):
        """Constructor.

        Do not use this method unless you know what you are doing; use
        `SerialPortStream.create()` instead.

        Parameters:
            device: the `pySerial` serial port object to manage in this stream.
                It must already be open.
        """
        try:
            from trio.lowlevel import FdStream
        except ImportError:
            raise RuntimeError("SerialPortStream is not supported on Windows") from None

        self._device = device
        self._fd_stream = FdStream(dup(self._device.fileno()))

    async def aclose(self) -> None:
        """Closes the serial port."""
        await self._fd_stream.aclose()

    async def receive_some(self, max_bytes: Optional[int] = None) -> bytes:
        result = await self._fd_stream.receive_some(max_bytes)
        if result:
            return result

        # Spurious EOF; this happens because POSIX serial port devices
        # may not return -1 with errno = WOULDBLOCK in case of an EOF
        # condition. So we wait for the port to become readable again. If it
        # becomes readable and _still_ returns no bytes, then this is a real
        # EOF.
        await wait_readable(self._fd_stream.fileno())
        try:
            return await self._fd_stream.receive_some(max_bytes)
        except Exception as ex:
            try:
                await self.aclose()
            except Exception:
                # This might fail as well, no worries
                pass
            raise ex

    async def send_all(self, data: bytes) -> None:
        """Sends some data over the serial port.

        Parameters:
            data: the data to send

        Raises:
            BusyResourceError: if another task is working with this stream
            BrokenResourceError: if something has gone wrong and the stream
                is broken
            ClosedResourceError: if you previously closed this stream object, or
                if another task closes this stream object while `send_all()`
                is running.
        """
        await self._fd_stream.send_all(data)

    async def wait_send_all_might_not_block(self) -> None:
        await self._fd_stream.wait_send_all_might_not_block()


if platform.system() == "Windows":
    SerialPortStream = _ThreadedSerialPortStream
else:
    SerialPortStream = _FdStreamBasedSerialPortStream


@create_connection.register("serial")
class SerialPortConnection(StreamConnectionBase):
    """Connection for a serial port."""

    def __init__(
        self,
        path: Union[str, int] = "",
        baud: int = 115200,
        stopbits: Union[int, float] = 1,
        *,
        vid: Optional[str] = None,
        pid: Optional[str] = None,
        manufacturer: Optional[str] = None,
        product: Optional[str] = None,
        serial_number: Optional[str] = None,
    ):
        """Constructor.

        Parameters:
            path: full path to the serial port to open, or a file descriptor
                for an already opened serial port. It may also be a string
                consisting of a USB vendor and product ID, in hexadecimal
                format, separated by a colon, in which case the first USB serial
                device matching the given vendor and product ID combination
                will be used. When the path is empty, the remaining arguments
                (e.g., `vid` and `pid`) will be used to find a matching USB
                serial device and the first matching device will be used.
            baud: the baud rate to use when opening the port
            stopbits: the number of stop bits to use. Must be
                1, 1.5 or 2.

        Keyword arguments:
            vid: specifies the USB vendor ID of the device to use. Must be in
                hexadecimal notation. Used only when the path is empty.
            pid: specifies the USB product ID of the device to use. Must be in
                hexadecimal notation. Used only when the path is empty.
            manufacturer: specifies the manufacturer of the device, as returned
                by the device itself on the USB bus. Used only when the path is
                empty and works for USB devices only. Glob patterns are allowed.
                Comparison is case insensitive.
            product: specifies the product name of the device, as returned
                by the device itself on the USB bus. Used only when the path is
                empty and works for USB devices only. Glob patterns are allowed.
                Comparison is case insensitive.
            serial_number: specifies the serial number of the device, as returned
                by the device itself on the USB bus. Used only when the path
                is empty and works for USB devices only.
        """
        super().__init__()

        self._path = path
        self._baud = baud
        self._stopbits = stopbits
        self._resolved_path: Optional[str] = None

        self._usb_properties = {
            "vid": vid,
            "pid": pid,
            "manufacturer": manufacturer,
            "product": product,
            "serial_number": serial_number,
        }

    @property
    def address(self) -> Optional[str]:
        """The real path of the serial port that the connection was resolved to
        (after matching USB vendor and product IDs), or `None` if the serial
        port is not connected.
        """
        return self._resolved_path

    async def _create_stream(self) -> Stream:
        from serial import STOPBITS_ONE, STOPBITS_ONE_POINT_FIVE, STOPBITS_TWO

        if self._path:
            match = re.match(
                "^(?P<vid>[0-9a-f]{4}):(?P<pid>[0-9a-f]{4})$",
                str(self._path),
                re.IGNORECASE,
            )
            if match:
                # path is most likely a USB vendor-product ID pair
                usb_properties = dict(
                    self._usb_properties, vid=match.group("vid"), pid=match.group("pid")
                )
                path = self._find_matching_usb_device(**usb_properties)
            else:
                path = self._path
        else:
            path = self._find_matching_usb_device(**self._usb_properties)

        if self._stopbits == 1:
            stopbits = STOPBITS_ONE
        elif self._stopbits == 1.5:
            stopbits = STOPBITS_ONE_POINT_FIVE
        elif self._stopbits == 2:
            stopbits = STOPBITS_TWO
        else:
            raise ValueError("unsupported stop bit count: {0!r}".format(self._stopbits))

        self._resolved_path = f"<fd: #{path}>" if isinstance(path, int) else str(path)

        return await SerialPortStream.create(
            path, baudrate=self._baud, stopbits=stopbits
        )

    async def _close(self) -> None:
        try:
            await super()._close()
        finally:
            self._resolved_path = None

    def _find_matching_usb_device(self, **kwds) -> str:
        """Finds a USB serial port that matches the given properties (vendor ID,
        product ID, manufacturer, product name and serial number) and returns
        its full pathname.

        See the constructor to learn more about the syntax of these arguments.
        """
        from serial.tools.list_ports import comports

        for port_info in comports():
            if self._port_info_matches(port_info, **kwds):
                return port_info.device

        kwds = {k: v for k, v in kwds.items() if v is not None}
        raise RuntimeError(f"No USB serial port matching specification: {kwds!r}")

    @staticmethod
    def _port_info_matches(
        port_info,
        *,
        vid: Optional[str] = None,
        pid: Optional[str] = None,
        manufacturer: Optional[str] = None,
        product: Optional[str] = None,
        serial_number: Optional[str] = None,
    ) -> bool:
        """Returns whether a USB serial port matches the given properties
        (vendor ID, product ID, manufacturer, product name and serial number).

        See the constructor to learn more about the syntax of these arguments.
        """
        try:
            vid_as_int = int(str(vid), 16) if vid is not None else None
            pid_as_int = int(str(pid), 16) if pid is not None else None
        except ValueError:
            return False

        if vid_as_int is not None and port_info.vid != vid_as_int:
            return False

        if pid_as_int is not None and port_info.pid != pid_as_int:
            return False

        if serial_number is not None and port_info.serial_number != serial_number:
            return False

        if manufacturer is not None and (
            port_info.manufacturer is None
            or not fnmatch(port_info.manufacturer.lower(), manufacturer.lower())
        ):
            return False

        if product is not None and (
            port_info.product is None
            or not fnmatch(port_info.product.lower(), product.lower())
        ):
            return False

        return True
