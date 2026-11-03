'''
src/core/results/error.py
'''
from __future__ import annotations
from dataclasses import dataclass
from .enums import ErrorCode
from typing import Any

@dataclass(frozen = True)
class Error:
    """
    Error class dataclass
    """
    code: ErrorCode
    msg: str
    details: dict[str, Any] | None


    @classmethod
    def connection_failed(cls, msg: str, details: dict[str, Any] | None) -> Error:
        '''Prebuilt connection failure error'''
        return cls(
            code = ErrorCode.CONNECTION_FAILURE,
            msg = msg,
            details = details
        )

    @classmethod
    def unknown_error(cls, msg: str, details: dict[str, Any]) -> Error:
        '''Prebuilt unknown error'''
        return cls(
            code = ErrorCode.UNKNOWN_ERROR,
            msg = msg,
            details = details
        )


    def __repr__(self) -> str:
        return (f'ERROR: {self.code} '
                f'MSG: {self.msg} '
                f'DETAILS: {self.details}')