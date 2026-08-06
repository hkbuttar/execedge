from datetime import datetime, timezone

from backtest.fill_model import FillModel
from backtest.order import ChildOrder
from lob.order_book import OrderBook


def make_book():
    book = OrderBook("test", "BTCUSD")
    book.load_snapshot(
        bids=[(99.0, 1.0), (98.5, 2.0)],
        asks=[(100.0, 1.0), (100.5, 2.0)],
        timestamp=datetime.now(timezone.utc),
    )
    return book


def test_zero_quantity_child_order_produces_no_fills():
    book = make_book()
    run = FillModel(temporary_impact_coef=0.0, permanent_impact_coef=0.0).new_run()
    child = ChildOrder(timestamp=datetime.now(timezone.utc), quantity=0.0, side="buy")

    result = run.execute(child, book)

    assert result.fills == []
    assert result.unfilled_quantity == 0.0


def test_order_within_depth_fully_fills_at_book_prices_with_no_impact():
    book = make_book()
    run = FillModel(temporary_impact_coef=0.0, permanent_impact_coef=0.0).new_run()
    child = ChildOrder(timestamp=datetime.now(timezone.utc), quantity=1.5, side="buy")

    result = run.execute(child, book)

    assert result.unfilled_quantity == 0.0
    assert [f.quantity for f in result.fills] == [1.0, 0.5]
    assert [f.price for f in result.fills] == [100.0, 100.5]


def test_order_exceeding_available_depth_leaves_unfilled_remainder():
    book = make_book()  # total ask depth = 3.0
    run = FillModel(temporary_impact_coef=0.0, permanent_impact_coef=0.0).new_run()
    child = ChildOrder(timestamp=datetime.now(timezone.utc), quantity=10.0, side="buy")

    result = run.execute(child, book)

    assert sum(f.quantity for f in result.fills) == 3.0
    assert result.unfilled_quantity == 7.0


def test_buy_temporary_impact_pushes_price_up():
    book = make_book()
    run = FillModel(temporary_impact_coef=0.1, permanent_impact_coef=0.0).new_run()
    child = ChildOrder(timestamp=datetime.now(timezone.utc), quantity=1.0, side="buy")

    result = run.execute(child, book)

    assert result.fills[0].price > 100.0  # walked price was 100.0, impact pushes it up


def test_sell_temporary_impact_pushes_price_down():
    book = make_book()
    run = FillModel(temporary_impact_coef=0.1, permanent_impact_coef=0.0).new_run()
    child = ChildOrder(timestamp=datetime.now(timezone.utc), quantity=1.0, side="sell")

    result = run.execute(child, book)

    assert result.fills[0].price < 99.0  # walked price was 99.0, impact pushes it down


def test_permanent_impact_carries_forward_within_a_run_but_not_across_runs():
    book = make_book()
    model = FillModel(temporary_impact_coef=0.0, permanent_impact_coef=0.1)

    run = model.new_run()
    first = run.execute(ChildOrder(timestamp=datetime.now(timezone.utc), quantity=1.0, side="buy"), book)
    second = run.execute(ChildOrder(timestamp=datetime.now(timezone.utc), quantity=1.0, side="buy"), book)
    assert second.fills[0].price > first.fills[0].price  # cumulative permanent offset within the run

    fresh_run = model.new_run()
    third = fresh_run.execute(ChildOrder(timestamp=datetime.now(timezone.utc), quantity=1.0, side="buy"), book)
    assert third.fills[0].price == first.fills[0].price  # new run starts with no accumulated offset
