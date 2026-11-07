'''
src/execution/domain/validation.py

Shared runtime checks for execution domain objects. Each raises TypeError for the
wrong type and ValueError for a bad value, with the field name in the message.
'''

import uuid
from datetime import datetime, timedelta
from decimal import Decimal


def check_non_blank_str(value: object, field: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a str, got {type(value).__name__}.")
    if not value.strip():
        raise ValueError(f"{field} must not be blank, got {value!r}.")


def check_uuid(value: object, field: str) -> None:
    if not isinstance(value, uuid.UUID):
        raise TypeError(f"{field} must be a UUID, got {type(value).__name__}.")


def check_positive_decimal(value: object, field: str) -> None:
    # Floats are refused: Decimal(0.1) silently becomes 0.1000000000000000055...
    if not isinstance(value, Decimal):
        raise TypeError(f"{field} must be a Decimal, got {type(value).__name__}.")
    if not value.is_finite():
        raise ValueError(f"{field} must be finite, got {value}.")
    if value <= 0:
        raise ValueError(f"{field} must be greater than 0, got {value}.")


def check_utc_datetime(value: object, field: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime, got {type(value).__name__}.")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be timezone-aware UTC, got {value!r}.")
