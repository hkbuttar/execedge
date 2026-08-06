"""Cross-venue validation: does the ranking of algorithms (does
Almgren-Chriss beat VWAP, does RL beat Almgren-Chriss) hold consistently
across Binance, Coinbase, and Kraken's real data, or diverge by venue?
Reported honestly either way. This is this project's replacement for a
cross-asset-class (equities-vs-crypto) robustness check -- everything
here is crypto by design, so robustness gets checked across real venues
instead, the axis of variation this project actually has.
"""

from dataclasses import dataclass

from backtest.experiment import ScenarioResult, is_robust


@dataclass
class VenueRanking:
    venue: str
    regime: str
    ranking: list  # scenario names, best (lowest mean bps) to worst
    means: dict  # scenario name -> mean bps
    robust: dict  # scenario name -> bool (is_robust for that scenario's own CI)


@dataclass
class CrossVenueReport:
    regime: str
    rankings: dict  # venue -> VenueRanking
    common_scenarios: list  # scenarios present in every venue's ranking
    consistent: bool  # True if the common-scenario ranking is identical everywhere
    common_ranking: list  # the shared ranking, best to worst, when consistent is True
    divergences: list  # human-readable description of where it diverges, if not


def rank_scenarios(results: list[ScenarioResult], venue: str, regime: str = "all") -> VenueRanking:
    """Extract one venue's ranking of scenarios (lowest/best mean shortfall
    bps first) for one regime, from that venue's own
    `backtest.experiment.run_bootstrap_experiment` output."""
    regime_results = [r for r in results if r.regime == regime]
    if len(regime_results) < 2:
        raise ValueError(
            f"need at least 2 scenarios in regime={regime!r} to rank, got {len(regime_results)}"
        )
    regime_results = sorted(regime_results, key=lambda r: r.bootstrap.point_estimate)
    return VenueRanking(
        venue=venue,
        regime=regime,
        ranking=[r.scenario for r in regime_results],
        means={r.scenario: r.bootstrap.point_estimate for r in regime_results},
        robust={r.scenario: is_robust(r) for r in regime_results},
    )


def compare_rankings_across_venues(rankings: dict) -> CrossVenueReport:
    """`rankings` is {venue_name: VenueRanking}, all for the same regime
    (raises if they aren't). Compares the ranking restricted to scenarios
    common to every venue -- a venue missing e.g. `vwap` (no real volume
    data fetched for it yet) shouldn't break the comparison for the
    scenarios it does have.
    """
    if len(rankings) < 2:
        raise ValueError("need at least 2 venues to cross-venue-compare")

    regimes = {ranking.regime for ranking in rankings.values()}
    if len(regimes) != 1:
        raise ValueError(f"all rankings must share one regime to compare, got {regimes}")
    regime = regimes.pop()

    venue_names = list(rankings)
    scenario_sets = [set(ranking.ranking) for ranking in rankings.values()]
    common_scenarios = set.intersection(*scenario_sets)
    if len(common_scenarios) < 2:
        raise ValueError(
            f"fewer than 2 scenarios are common across all venues ({sorted(common_scenarios)}) "
            f"-- nothing to cross-venue-compare"
        )

    restricted = {
        venue: [s for s in ranking.ranking if s in common_scenarios]
        for venue, ranking in rankings.items()
    }

    reference_venue = venue_names[0]
    reference_order = restricted[reference_venue]
    consistent = all(restricted[v] == reference_order for v in venue_names)

    divergences = []
    if not consistent:
        for v in venue_names[1:]:
            if restricted[v] != reference_order:
                divergences.append(
                    f"{reference_venue} ranks {reference_order} but {v} ranks {restricted[v]}"
                )

    return CrossVenueReport(
        regime=regime,
        rankings=rankings,
        common_scenarios=sorted(common_scenarios),
        consistent=consistent,
        common_ranking=reference_order if consistent else [],
        divergences=divergences,
    )
