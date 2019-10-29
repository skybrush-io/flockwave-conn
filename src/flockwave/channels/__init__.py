"""Class that implements a Trio-style channel object that takes data from a
ReadableConnection_ and yields parsed message objects.
"""

from .encoder import EncoderChannel
from .message import MessageChannel
from .parser import ParserChannel

__all__ = ("ParserChannel", "EncoderChannel", "MessageChannel")
