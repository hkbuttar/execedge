from risk.triggers import RiskState, shortfall_trigger, volatility_trigger


def test_volatility_trigger_fires_above_threshold():
    check = volatility_trigger(max_realized_vol=0.01)
    assert check(RiskState(realized_vol=0.02, cumulative_cost_bps=0.0)) is not None
    assert check(RiskState(realized_vol=0.005, cumulative_cost_bps=0.0)) is None


def test_volatility_trigger_ignores_none_vol():
    check = volatility_trigger(max_realized_vol=0.01)
    assert check(RiskState(realized_vol=None, cumulative_cost_bps=0.0)) is None


def test_shortfall_trigger_fires_above_threshold():
    check = shortfall_trigger(max_cumulative_cost_bps=5.0)
    assert check(RiskState(realized_vol=None, cumulative_cost_bps=10.0)) is not None
    assert check(RiskState(realized_vol=None, cumulative_cost_bps=2.0)) is None


def test_trigger_reason_mentions_the_threshold():
    check = shortfall_trigger(max_cumulative_cost_bps=5.0)
    reason = check(RiskState(realized_vol=None, cumulative_cost_bps=10.0))
    assert "5" in reason
    assert "10" in reason
