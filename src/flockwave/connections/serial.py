"""Connection for a serial port."""

from __future__ import absolute_import, print_function

import re

from fnmatch import fnmatch
from os import dup
from trio.abc import Stream
from trio.lowlevel import wait_readable
from typing import Optional, Union

from .factory import create_connection
from .stream import StreamConnectionBase

__all__ = ("SerialPortConnection",)


class SerialPortStream(Stream):
    """A Trio stream implementation that talks to a serial port using
    PySerial in a separate thread.
    """

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

        return cls(Serial(timeout=0, *args, **kwds))

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
            raise RuntimeError("SerialPortStream is not supported on Windows")

        self._device = device
        self._device.nonblocking()
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
        return await self._fd_stream.receive_some(max_bytes)

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
        super(SerialPortConnection, self).__init__()

        self._path = path
        self._baud = baud
        self._stopbits = stopbits

        self._usb_properties = {
            "vid": vid,
            "pid": pid,
            "manufacturer": manufacturer,
            "product": product,
            "serial_number": serial_number,
        }

    async def _create_stream(self) -> Stream:
        from serial import STOPBITS_ONE, STOPBITS_ONE_POINT_FIVE, STOPBITS_TWO

        if self._path:
            match = re.match(
                "^(?P<vid>[0-9a-f]{4}):(?P<pid>[0-9a-f]{4})$", self._path, re.IGNORECASE
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

        return await SerialPortStream.create(
            path, baudrate=self._baud, stopbits=stopbits
        )

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
            vid = int(str(vid), 16) if vid is not None else None
            pid = int(str(pid), 16) if pid is not None else None
        except ValueError:
            return False

        if vid is not None and port_info.vid != vid:
            return False

        if pid is not None and port_info.pid != pid:
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
