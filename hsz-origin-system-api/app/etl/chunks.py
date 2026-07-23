from collections.abc import Iterator, Sequence
from typing import TypeVar

T = TypeVar("T")


def chunked(values: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    if size <= 0:
        raise ValueError("batch size must be positive")
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]
