'''
tests/integration/test_execution_alpaca_paper.py

Places a REAL 1-share order on the Alpaca PAPER account and follows it until it finishes.
Skipped unless RUN_INTEGRATION=1. Needs ALPACA_API_KEY / ALPACA_SECRET_KEY in the
environment or in .env at the repo root. Refuses to run unless ALPACA_PAPER is unset or true.

During market hours the order should fill; outside them it stays open and is canceled at the end.
'''

import os
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("alpaca")

from src.execution.adapters.alpaca_broker import AlpacaBroker  # noqa: E402
from src.execution.domain.enums import OrderSide, OrderStatus  # noqa: E402
from src.execution.domain.events import FillEvent, OrderSubmittedEvent  # noqa: E402
from src.execution.domain.order import Order  # noqa: E402

pytestmark = pytest.mark.integration

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
SYMBOL = os.environ.get("ALPACA_TEST_SYMBOL", "AAPL")


def read_env() -> dict[str, str]:
    '''os.environ plus KEY=VALUE lines from .env (os.environ wins). No extra dependency.'''
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    env.update(os.environ)
    return env


@pytest.fixture
def broker() -> AlpacaBroker:
    env = read_env()
    if env.get("ALPACA_PAPER", "true").strip().lower() == "false":
        pytest.fail("Refusing to run the integration test against a LIVE account.")
    if not env.get("ALPACA_API_KEY") or not env.get("ALPACA_SECRET_KEY"):
        pytest.skip("ALPACA_API_KEY / ALPACA_SECRET_KEY are not set.")
    return AlpacaBroker.from_env(env)


def test_one_share_paper_order_round_trip(broker: AlpacaBroker):
    order = Order(client_order_id=uuid.uuid4(), symbol=SYMBOL, side=OrderSide.BUY,
                  quantity=Decimal("1"), created_at=datetime.now(timezone.utc))

    submitted = broker.submit_order(order)
    assert submitted.is_success, submitted.error
    assert submitted.value is not None
    broker_order_id = submitted.value
    order.mark_submitted(broker_order_id)
    print(f"\nSubmitted {order.client_order_id} -> Alpaca {broker_order_id}")

    # The same client_order_id again must be refused by Alpaca (second idempotency net).
    duplicate = broker.submit_order(order)
    assert not duplicate.is_success

    found = broker.find_order(order.client_order_id)
    assert found.is_success and found.value is not None and found.value.broker_order_id == broker_order_id

    deadline = time.monotonic() + 30
    while not order.is_terminal and time.monotonic() < deadline:
        update = broker.get_order_status(broker_order_id)
        assert update.is_success, update.error
        assert update.value is not None
        for fill in update.value.fills:
            if fill not in order.fills:
                order.apply_fill(fill)
                print(f"Fill {fill.quantity} @ {fill.price}")
        if update.value.status in (OrderStatus.CANCELED, OrderStatus.REJECTED) and not order.is_terminal:
            pytest.fail(f"Order ended {update.value.status}: {update.value.reason}")
        time.sleep(1)

    if not order.is_terminal:
        print("Not filled within 30s (market closed?); canceling.")
        assert broker.cancel_order(broker_order_id).is_success
        pytest.skip("Order accepted but not filled: run during market hours for the fill milestone.")

    assert order.status is OrderStatus.FILLED
    assert order.filled_quantity == Decimal("1")


def test_risk_approval_to_paper_fill_through_the_manager(broker: AlpacaBroker):
    '''The Week 3 milestone: RiskApprovedEvent -> ExecutionManager -> Alpaca paper -> FillEvent.'''
    from tests.unit.test_execution_manager import Harness, approve, make_signal  # builders, no network

    h = Harness(broker=broker)
    h.send(approve(make_signal(units=Decimal("1"), symbol=SYMBOL)))
    assert h.of_type(OrderSubmittedEvent), h.published

    deadline = time.monotonic() + 30
    while not h.of_type(FillEvent) and time.monotonic() < deadline:
        h.poll()
        time.sleep(1)

    if not h.of_type(FillEvent):
        for order in h.manager.open_orders:
            assert order.broker_order_id is not None
            broker.cancel_order(order.broker_order_id)
        pytest.skip("Order accepted but not filled: run during market hours for the fill milestone.")

    (fill,) = h.of_type(FillEvent)
    assert fill.order_status is OrderStatus.FILLED and fill.filled_quantity == Decimal("1")
