from datetime import datetime, timedelta, timezone

from backtest.metrics import implementation_shortfall
from backtest.order import Fill, ParentOrder

NOW = datetime.now(timezone.utc)


def make_parent(side, quantity=10.0):
    return ParentOrder(
        venue="test", symbol="BTCUSD", side=side, quantity=quantity,
        start_time=NOW, end_time=NOW + timedelta(minutes=5),
    )


def test_fully_filled_buy_at_arrival_price_has_zero_shortfall():
    parent = make_parent("buy")
    fills = [Fill(timestamp=NOW, price=100.0, quantity=10.0)]
    result = implementation_shortfall(parent, fills, arrival_price=100.0, end_price=100.0)
    assert result.executed_cost == 0.0
    assert result.opportunity_cost == 0.0
    assert result.total_cost == 0.0


def test_buy_filled_above_arrival_price_is_a_cost():
    parent = make_parent("buy")
    fills = [Fill(timestamp=NOW, price=101.0, quantity=10.0)]
    result = implementation_shortfall(parent, fills, arrival_price=100.0, end_price=100.0)
    assert result.executed_cost == 10.0  # (101-100)*10
    assert result.total_cost == 10.0
    assert result.total_cost_bps > 0


def test_sell_filled_below_arrival_price_is_a_cost():
    parent = make_parent("sell")
    fills = [Fill(timestamp=NOW, price=99.0, quantity=10.0)]
    result = implementation_shortfall(parent, fills, arrival_price=100.0, end_price=100.0)
    assert result.executed_cost == 10.0  # (99-100)*10*(-1)
    assert result.total_cost == 10.0


def test_unfilled_buy_quantity_charged_opportunity_cost_if_price_rose():
    parent = make_parent("buy", quantity=10.0)
    fills = [Fill(timestamp=NOW, price=100.0, quantity=6.0)]  # 4 unfilled
    result = implementation_shortfall(parent, fills, arrival_price=100.0, end_price=105.0)
    assert result.unfilled_quantity == 4.0
    assert result.opportunity_cost == 20.0  # 4 * (105-100)
    assert result.total_cost == 20.0


def test_unfilled_sell_quantity_credited_if_price_rose():
    parent = make_parent("sell", quantity=10.0)
    fills = [Fill(timestamp=NOW, price=100.0, quantity=6.0)]
    result = implementation_shortfall(parent, fills, arrival_price=100.0, end_price=105.0)
    # missing the chance to sell higher is a cost for a sell order too,
    # since side_sign flips the direction of "hurts"
    assert result.opportunity_cost == -20.0  # 4 * (105-100) * (-1)
