"""Class that implements a Trio-style channel object that takes data from a
ReadableConnection_ and yields parsed message objects.
"""

from .encoder import EncoderChannel
from .lossy import create_lossy_channel
from .message import BroadcastMessageChannel, MessageChannel
from .parser import ParserChannel

__all__ = (
    "BroadcastMessageChannel",
    "ParserChannel",
    "EncoderChannel",
    "MessageChannel",
    "create_lossy_channel",
)
