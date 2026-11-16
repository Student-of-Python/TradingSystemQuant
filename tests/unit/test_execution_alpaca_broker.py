'''
tests/unit/test_execution_alpaca_broker.py

AlpacaBroker against a fake TradingClient that returns recorded Alpaca JSON (parsed into
the SDK's real Order model) or raises the SDK's real errors. No network.
'''

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

pytest.importorskip("alpaca", reason="alpaca-py is not installed (pip install -r src/execution/requirements.txt)")

import requests  # noqa: E402  (installed with alpaca-py)
from alpaca.common.exceptions import APIError  # noqa: E402
from alpaca.trading.models import Order as AlpacaOrder  # noqa: E402
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest  # noqa: E402

from src.core.results import ErrorCode  # noqa: E402
from src.execution.adapters.alpaca_broker import STATUS_MAP, AlpacaBroker, to_error  # noqa: E402
from src.execution.domain.enums import OrderSide, OrderStatus  # noqa: E402
from src.execution.domain.order import Order  # noqa: E402
from src.execution.ports import BrokerErrorCode, BrokerPort, broker_error_code  # noqa: E402

NOW = datetime(2026, 11, 17, 15, 0, tzinfo=timezone.utc)
CLIENT_ID = uuid.UUID("0b7e0b7c-6a49-5d55-9b39-5a3c1b7d9f10")
ALPACA_ID = "61e69015-8549-4bfd-b9c3-01e75843f47d"


def recorded_order(**overrides: Any) -> dict[str, Any]:
    '''A paper-trading market order as Alpaca's REST API returns it.'''
    data: dict[str, Any] = {
        "id": ALPACA_ID,
        "client_order_id": str(CLIENT_ID),
        "created_at": "2026-11-17T15:00:00.123456Z",
        "updated_at": "2026-11-17T15:00:00.123456Z",
        "submitted_at": "2026-11-17T15:00:00.120000Z",
        "filled_at": None,
        "expired_at": None,
        "canceled_at": None,
        "failed_at": None,
        "replaced_at": None,
        "replaced_by": None,
        "replaces": None,
        "asset_id": "b0b6dd9d-8b9b-48a9-ba46-b9d54906e415",
        "symbol": "AAPL",
        "asset_class": "us_equity",
        "notional": None,
        "qty": "10",
        "filled_qty": "0",
        "filled_avg_price": None,
        "order_class": "simple",
        "order_type": "market",
        "type": "market",
        "side": "buy",
        "time_in_force": "day",
        "limit_price": None,
        "stop_price": None,
        "status": "accepted",
        "extended_hours": False,
        "legs": None,
        "trail_percent": None,
        "trail_price": None,
        "hwm": None,
        "position_intent": "buy_to_open",
    }
    data.update(overrides)
    return data


def model(**overrides: Any) -> AlpacaOrder:
    return AlpacaOrder(**recorded_order(**overrides))


def api_error(status: int, message: str, code: int = 40010000) -> APIError:
    response = requests.Response()
    response.status_code = status
    http_error = requests.HTTPError(f"{status} error", response=response)
    return APIError(json.dumps({"code": code, "message": message}), http_error)


class FakeClient:
    '''Each method returns (or raises) the next queued answer for it.'''

    def __init__(self) -> None:
        self.answers: dict[str, list[Any]] = {}
        self.calls: list[tuple[str, Any]] = []

    def queue(self, method: str, *answers: Any) -> None:
        self.answers.setdefault(method, []).extend(answers)

    def _answer(self, method: str, arg: Any) -> Any:
        self.calls.append((method, arg))
        answer = self.answers[method].pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def submit_order(self, order_data: Any) -> Any:
        return self._answer("submit_order", order_data)

    def cancel_order_by_id(self, order_id: Any) -> Any:
        return self._answer("cancel_order_by_id", order_id)

    def get_order_by_id(self, order_id: Any, filter: Any = None) -> Any:
        return self._answer("get_order_by_id", order_id)

    def get_order_by_client_id(self, client_id: str) -> Any:
        return self._answer("get_order_by_client_id", client_id)

    def get_orders(self, filter: Any = None) -> Any:
        return self._answer("get_orders", filter)


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def broker(client: FakeClient) -> AlpacaBroker:
    return AlpacaBroker(client, clock=lambda: NOW)


def make_order(quantity: str = "10", side: OrderSide = OrderSide.BUY) -> Order:
    return Order(client_order_id=CLIENT_ID, symbol="AAPL", side=side, quantity=Decimal(quantity), created_at=NOW)


def status_of(broker: AlpacaBroker, client: FakeClient, **overrides: Any):
    client.queue("get_order_by_id", model(**overrides))
    result = broker.get_order_status(ALPACA_ID)
    assert result.is_success, result.error
    assert result.value is not None
    return result.value


def test_satisfies_the_broker_port(broker):
    port: BrokerPort = broker  # checked by the type checker
    assert callable(port.list_open_orders)


# ---------------------------------------------------------------- submit


@pytest.mark.parametrize("side, alpaca_side", [(OrderSide.BUY, "buy"), (OrderSide.SELL, "sell")])
def test_submit_sends_a_day_market_order_with_our_client_order_id(broker, client, side, alpaca_side):
    client.queue("submit_order", model(status="pending_new", side=alpaca_side))

    result = broker.submit_order(make_order("2.5", side))

    assert result.is_success and result.value == ALPACA_ID
    ((method, request),) = client.calls
    assert method == "submit_order" and isinstance(request, MarketOrderRequest)
    assert request.symbol == "AAPL"
    assert request.qty == 2.5
    assert request.side.value == alpaca_side
    assert request.time_in_force.value == "day"
    assert request.client_order_id == str(CLIENT_ID)


def test_submit_accepts_a_raw_dict_response(broker, client):
    client.queue("submit_order", recorded_order())

    assert broker.submit_order(make_order()).value == ALPACA_ID


def test_submit_refuses_a_quantity_a_float_cannot_carry_exactly(broker, client):
    result = broker.submit_order(make_order("0.1000000000000000000001"))

    assert result.error is not None and result.error.code is ErrorCode.INVALID_DATA
    assert client.calls == []  # nothing was sent


@pytest.mark.parametrize("error, code", [
    (api_error(403, "insufficient buying power", 40310000), BrokerErrorCode.INSUFFICIENT_FUNDS),
    (api_error(422, "client_order_id must be unique", 40010001), BrokerErrorCode.DUPLICATE_ORDER),
    (api_error(422, "asset ZZZZ is not tradable", 42210000), BrokerErrorCode.BROKER_REJECTED),
    (api_error(401, "request is not authorized", 40110000), BrokerErrorCode.BROKER_REJECTED),
])
def test_submit_api_errors_become_broker_codes(broker, client, error, code):
    client.queue("submit_order", error)

    result = broker.submit_order(make_order())

    assert not result.is_success
    assert broker_error_code(result.error) is code


@pytest.mark.parametrize("error", [
    requests.ConnectionError("connection refused"),
    requests.Timeout("read timed out"),
    api_error(500, "internal server error"),
    api_error(503, "service unavailable"),
    api_error(429, "rate limit exceeded"),
])
def test_submit_network_and_server_errors_are_connection_failures(broker, client, error):
    client.queue("submit_order", error)

    result = broker.submit_order(make_order())

    assert result.error is not None and result.error.code is ErrorCode.CONNECTION_FAILURE


def test_submit_unexpected_exception_is_an_unknown_error(broker, client):
    client.queue("submit_order", RuntimeError("boom"))

    result = broker.submit_order(make_order())

    assert result.error is not None and result.error.code is ErrorCode.UNKNOWN_ERROR
    assert "boom" in result.error.msg


def test_api_error_with_a_non_json_body_still_translates():
    error = APIError("<html>bad gateway</html>", None)

    assert broker_error_code(to_error(error)) is BrokerErrorCode.BROKER_REJECTED


# ---------------------------------------------------------------- cancel


def test_cancel_success(broker, client):
    client.queue("cancel_order_by_id", None)

    assert broker.cancel_order(ALPACA_ID).is_success
    assert client.calls == [("cancel_order_by_id", ALPACA_ID)]


def test_cancel_of_a_filled_order_is_a_broker_rejection(broker, client):
    client.queue("cancel_order_by_id", api_error(422, 'order is already in "filled" state', 42210000))

    assert broker_error_code(broker.cancel_order(ALPACA_ID).error) is BrokerErrorCode.BROKER_REJECTED


def test_cancel_unknown_order_is_not_found(broker, client):
    client.queue("cancel_order_by_id", api_error(404, "order not found", 40410000))

    assert broker_error_code(broker.cancel_order(ALPACA_ID).error) is BrokerErrorCode.ORDER_NOT_FOUND


# ---------------------------------------------------------------- status mapping


@pytest.mark.filterwarnings("ignore:OrderStatus.PENDING_REVIEW is deprecated:DeprecationWarning")
@pytest.mark.parametrize("alpaca_status", [s for s, ours in STATUS_MAP.items() if ours is None])
def test_open_statuses_without_fills_are_submitted(broker, client, alpaca_status):
    update = status_of(broker, client, status=alpaca_status)

    assert update.status is OrderStatus.SUBMITTED
    assert update.fills == () and update.reason is None


@pytest.mark.parametrize("alpaca_status", ["pending_cancel", "done_for_day", "partially_filled"])
def test_open_statuses_with_fills_are_partially_filled(broker, client, alpaca_status):
    update = status_of(broker, client, status=alpaca_status, filled_qty="4", filled_avg_price="187.5")

    assert update.status is OrderStatus.PARTIALLY_FILLED


@pytest.mark.parametrize("alpaca_status, ours", [
    ("canceled", OrderStatus.CANCELED),
    ("expired", OrderStatus.CANCELED),
    ("replaced", OrderStatus.CANCELED),
    ("rejected", OrderStatus.REJECTED),
])
def test_finished_statuses_carry_a_reason(broker, client, alpaca_status, ours):
    update = status_of(broker, client, status=alpaca_status)

    assert update.status is ours
    assert update.reason == f"Alpaca order status: {alpaca_status}."


def test_rejected_after_a_partial_fill_becomes_canceled_and_keeps_the_fill(broker, client):
    update = status_of(broker, client, status="rejected", filled_qty="3", filled_avg_price="10")

    assert update.status is OrderStatus.CANCELED
    assert [f.quantity for f in update.fills] == [Decimal("3")]


def test_every_alpaca_status_is_mapped():
    from alpaca.trading.enums import OrderStatus as AlpacaStatus

    assert {s.value for s in AlpacaStatus} == set(STATUS_MAP)


def test_unknown_status_is_invalid_data(broker, client):
    raw = recorded_order()
    raw["status"] = "brand_new_status"
    client.queue("get_order_by_id", raw)  # raw dict: the SDK model would refuse it first

    result = broker.get_order_status(ALPACA_ID)

    assert result.error is not None and result.error.code is ErrorCode.INVALID_DATA


def test_foreign_client_order_id_is_invalid_data(broker, client):
    client.queue("get_order_by_id", model(client_order_id="placed-by-hand"))

    result = broker.get_order_status(ALPACA_ID)

    assert result.error is not None and result.error.code is ErrorCode.INVALID_DATA


def test_status_network_error_is_a_connection_failure(broker, client):
    client.queue("get_order_by_id", requests.ConnectionError("down"))

    result = broker.get_order_status(ALPACA_ID)

    assert result.error is not None and result.error.code is ErrorCode.CONNECTION_FAILURE


# ---------------------------------------------------------------- fills


def test_full_fill_in_one_poll(broker, client):
    update = status_of(broker, client, status="filled", filled_qty="10", filled_avg_price="187.23",
                       filled_at="2026-11-17T15:00:01.5Z")

    assert update.status is OrderStatus.FILLED
    (fill,) = update.fills
    assert fill.fill_id == f"{ALPACA_ID}:10"
    assert fill.client_order_id == CLIENT_ID
    assert (fill.quantity, fill.price) == (Decimal("10"), Decimal("187.23"))
    assert fill.timestamp == datetime(2026, 11, 17, 15, 0, 1, 500000, tzinfo=timezone.utc)


def test_cumulative_fills_become_one_fill_per_increase_with_exact_prices(broker, client):
    first = status_of(broker, client, status="partially_filled", filled_qty="4", filled_avg_price="100")
    again = status_of(broker, client, status="partially_filled", filled_qty="4", filled_avg_price="100")
    last = status_of(broker, client, status="filled", filled_qty="10", filled_avg_price="106")

    assert [f.fill_id for f in first.fills] == [f"{ALPACA_ID}:4"]
    assert again.fills == first.fills  # no new fill when nothing changed
    assert [(f.quantity, f.price) for f in last.fills] == [(Decimal("4"), Decimal("100")), (Decimal("6"), Decimal("110"))]
    assert sum(f.notional for f in last.fills) == Decimal("1060")  # 10 x avg 106


def test_fractional_fill_ids_are_normalized(broker, client):
    update = status_of(broker, client, status="filled", qty="0.5", filled_qty="0.500", filled_avg_price="200")

    assert update.fills[0].fill_id == f"{ALPACA_ID}:0.5"


def test_fill_without_a_timestamp_uses_the_clock(broker, client):
    raw = recorded_order(status="filled", filled_qty="10", filled_avg_price="1")
    raw["filled_at"] = None
    raw.pop("updated_at")
    client.queue("get_order_by_id", raw)

    update = broker.get_order_status(ALPACA_ID).value

    assert update is not None and update.fills[0].timestamp == NOW


def test_fill_without_an_average_price_is_invalid_data(broker, client):
    client.queue("get_order_by_id", model(status="partially_filled", filled_qty="4", filled_avg_price=None))

    result = broker.get_order_status(ALPACA_ID)

    assert result.error is not None and result.error.code is ErrorCode.INVALID_DATA


def test_filled_qty_going_down_keeps_the_known_fills(broker, client):
    status_of(broker, client, status="partially_filled", filled_qty="4", filled_avg_price="100")

    update = status_of(broker, client, status="partially_filled", filled_qty="2", filled_avg_price="100")

    assert [f.quantity for f in update.fills] == [Decimal("4")]


# ---------------------------------------------------------------- find_order


def test_find_order_looks_up_by_our_client_order_id(broker, client):
    client.queue("get_order_by_client_id", model(status="new"))

    result = broker.find_order(CLIENT_ID)

    assert result.is_success and result.value is not None
    assert result.value.broker_order_id == ALPACA_ID and result.value.status is OrderStatus.SUBMITTED
    assert client.calls == [("get_order_by_client_id", str(CLIENT_ID))]


def test_find_order_never_received_is_not_found(broker, client):
    client.queue("get_order_by_client_id", api_error(404, "order not found", 40410000))

    assert broker_error_code(broker.find_order(CLIENT_ID).error) is BrokerErrorCode.ORDER_NOT_FOUND


# ---------------------------------------------------------------- list_open_orders


def test_list_open_orders_requests_open_orders_and_builds_records(broker, client):
    client.queue("get_orders", [
        model(status="partially_filled", side="sell", qty="10", filled_qty="4", filled_avg_price="50"),
    ])

    result = broker.list_open_orders()

    assert result.is_success and result.value is not None
    ((_, request),) = client.calls
    assert isinstance(request, GetOrdersRequest) and request.status is not None and request.status.value == "open"
    (record,) = result.value
    assert record.client_order_id == CLIENT_ID
    assert (record.symbol, record.side, record.quantity) == ("AAPL", OrderSide.SELL, Decimal("10"))
    assert record.created_at == datetime(2026, 11, 17, 15, 0, 0, 123456, tzinfo=timezone.utc)
    assert record.update.status is OrderStatus.PARTIALLY_FILLED
    assert [f.quantity for f in record.update.fills] == [Decimal("4")]


def test_list_open_orders_skips_foreign_and_notional_orders(broker, client):
    other = "71e69015-8549-4bfd-b9c3-01e75843f47d"
    client.queue("get_orders", [
        model(id=other, client_order_id="placed-by-hand"),
        model(id="81e69015-8549-4bfd-b9c3-01e75843f47d", qty=None, notional="100"),
        model(),
    ])

    result = broker.list_open_orders()

    assert result.value is not None
    assert [r.update.broker_order_id for r in result.value] == [ALPACA_ID]


def test_list_open_orders_failure_is_a_result(broker, client):
    client.queue("get_orders", requests.ConnectionError("down"))

    result = broker.list_open_orders()

    assert result.error is not None and result.error.code is ErrorCode.CONNECTION_FAILURE


# ---------------------------------------------------------------- from_env


def test_from_env_requires_both_keys():
    with pytest.raises(ValueError, match="ALPACA_API_KEY"):
        AlpacaBroker.from_env({"ALPACA_API_KEY": "k"})


@pytest.mark.parametrize("paper_value, paper", [(None, True), ("true", True), ("FALSE", False), ("no", True)])
def test_from_env_defaults_to_paper(monkeypatch, paper_value, paper):
    import src.execution.adapters.alpaca_broker as module

    seen: dict[str, Any] = {}
    monkeypatch.setattr(module, "TradingClient", lambda **kwargs: seen.update(kwargs) or FakeClient())
    env = {"ALPACA_API_KEY": "k", "ALPACA_SECRET_KEY": "s"}
    if paper_value is not None:
        env["ALPACA_PAPER"] = paper_value

    AlpacaBroker.from_env(env)

    assert seen == {"api_key": "k", "secret_key": "s", "paper": paper}
