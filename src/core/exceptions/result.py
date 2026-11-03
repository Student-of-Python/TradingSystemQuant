'''
src/core/exceptions/result.py
'''
from __future__ import annotations
from dataclasses import dataclass
from error import Error


@dataclass(frozen = True)
class Result[T]:
    value: T | None = None
    error: Error | None = None

    @property
    def is_success(self) -> bool:
        '''Returns true if result is sucessful'''
        return self.error is None

    @classmethod
    def successful(cls, value: T) -> Result[T]:
        ''''''
        return cls(value = value)

    @classmethod
    def failure(cls, error: Error) -> Result[None]:
        return cls(error = error)
