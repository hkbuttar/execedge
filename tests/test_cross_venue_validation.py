import pytest

from backtest.bootstrap import BootstrapResult
from backtest.experiment import ScenarioResult
from venues.cross_venue_validation import compare_rankings_across_venues, rank_scenarios


def make_result(scenario, regime, point_estimate):
    return ScenarioResult(
        scenario=scenario, regime=regime,
        bootstrap=BootstrapResult(
            point_estimate=point_estimate,
            ci_low=point_estimate - 0.1, ci_high=point_estimate + 0.1,
            n_samples=10, n_resamples=1000, confidence_level=0.95,
        ),
        per_window_bps=[],
    )


def test_rank_scenarios_orders_best_to_worst():
    results = [
        make_result("naive", "all", 10.0),
        make_result("twap", "all", 5.0),
        make_result("ac", "all", 2.0),
    ]
    ranking = rank_scenarios(results, venue="binance")
    assert ranking.ranking == ["ac", "twap", "naive"]
    assert ranking.means["ac"] == 2.0
    assert ranking.venue == "binance"
    assert ranking.regime == "all"


def test_rank_scenarios_filters_by_regime():
    results = [
        make_result("naive", "all", 10.0),
        make_result("twap", "all", 5.0),
        make_result("naive", "calm", 1.0),
        make_result("twap", "calm", 3.0),
    ]
    ranking = rank_scenarios(results, venue="binance", regime="calm")
    assert ranking.ranking == ["naive", "twap"]


def test_rank_scenarios_raises_with_fewer_than_two():
    results = [make_result("naive", "all", 10.0)]
    with pytest.raises(ValueError):
        rank_scenarios(results, venue="binance")


def test_compare_rankings_consistent_across_venues():
    binance_results = [make_result("naive", "all", 10.0), make_result("twap", "all", 5.0)]
    coinbase_results = [make_result("naive", "all", 20.0), make_result("twap", "all", 8.0)]
    rankings = {
        "binance": rank_scenarios(binance_results, "binance"),
        "coinbase": rank_scenarios(coinbase_results, "coinbase"),
    }
    report = compare_rankings_across_venues(rankings)
    assert report.consistent is True
    assert report.common_ranking == ["twap", "naive"]
    assert report.divergences == []


def test_compare_rankings_detects_divergence():
    binance_results = [make_result("naive", "all", 10.0), make_result("twap", "all", 5.0)]
    # on kraken, naive beats twap -- the opposite order
    kraken_results = [make_result("naive", "all", 3.0), make_result("twap", "all", 9.0)]
    rankings = {
        "binance": rank_scenarios(binance_results, "binance"),
        "kraken": rank_scenarios(kraken_results, "kraken"),
    }
    report = compare_rankings_across_venues(rankings)
    assert report.consistent is False
    assert report.common_ranking == []
    assert len(report.divergences) == 1
    assert "binance" in report.divergences[0]
    assert "kraken" in report.divergences[0]


def test_compare_rankings_uses_only_common_scenarios():
    # binance has an extra scenario (vwap) that coinbase doesn't
    binance_results = [
        make_result("naive", "all", 10.0),
        make_result("twap", "all", 5.0),
        make_result("vwap", "all", 1.0),
    ]
    coinbase_results = [make_result("naive", "all", 10.0), make_result("twap", "all", 5.0)]
    rankings = {
        "binance": rank_scenarios(binance_results, "binance"),
        "coinbase": rank_scenarios(coinbase_results, "coinbase"),
    }
    report = compare_rankings_across_venues(rankings)
    assert report.common_scenarios == ["naive", "twap"]
    assert report.consistent is True  # both agree twap beats naive, ignoring vwap
    assert report.common_ranking == ["twap", "naive"]


def test_compare_rankings_raises_with_fewer_than_two_venues():
    binance_results = [make_result("naive", "all", 10.0), make_result("twap", "all", 5.0)]
    rankings = {"binance": rank_scenarios(binance_results, "binance")}
    with pytest.raises(ValueError):
        compare_rankings_across_venues(rankings)


def test_compare_rankings_raises_with_fewer_than_two_common_scenarios():
    binance_results = [make_result("naive", "all", 10.0), make_result("twap", "all", 5.0)]
    coinbase_results = [make_result("naive", "all", 10.0), make_result("vwap", "all", 5.0)]
    rankings = {
        "binance": rank_scenarios(binance_results, "binance"),
        "coinbase": rank_scenarios(coinbase_results, "coinbase"),
    }
    with pytest.raises(ValueError):
        compare_rankings_across_venues(rankings)


def test_compare_rankings_raises_on_mismatched_regimes():
    binance_results = [make_result("naive", "all", 10.0), make_result("twap", "all", 5.0)]
    coinbase_results = [make_result("naive", "calm", 10.0), make_result("twap", "calm", 5.0)]
    rankings = {
        "binance": rank_scenarios(binance_results, "binance", regime="all"),
        "coinbase": rank_scenarios(coinbase_results, "coinbase", regime="calm"),
    }
    with pytest.raises(ValueError):
        compare_rankings_across_venues(rankings)
