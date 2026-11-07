'''
src/execution/domain/fill.py

Fill value object: one broker execution against an order.
An order of 10 shares may be completed by several fills (e.g. 4 then 6).
'''

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.execution.domain.validation import (
    check_non_blank_str,
    check_positive_decimal,
    check_utc_datetime,
    check_uuid,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Fill:
    '''
    fill_id (str): The broker's id for this execution. Used to ignore duplicate fill reports.
    client_order_id (UUID): The order this fill belongs to.
    price (Decimal): Execution price per unit. Must be > 0.
    quantity (Decimal): Units executed in this fill. Must be > 0.
    timestamp (datetime): When the broker executed it. Must be timezone-aware UTC.
    '''
    fill_id: str
    client_order_id: uuid.UUID
    price: Decimal
    quantity: Decimal
    timestamp: datetime

    def __post_init__(self) -> None:
        check_non_blank_str(self.fill_id, "fill_id")
        check_uuid(self.client_order_id, "client_order_id")
        check_positive_decimal(self.price, "price")
        check_positive_decimal(self.quantity, "quantity")
        check_utc_datetime(self.timestamp, "timestamp")

    @property
    def notional(self) -> Decimal:
        '''Cash value of this fill (price x quantity).'''
        return self.price * self.quantity
