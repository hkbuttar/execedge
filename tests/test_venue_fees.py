from venues.fees import VENUE_FEE_SCHEDULES


def test_all_three_venues_present():
    assert set(VENUE_FEE_SCHEDULES) == {"binance", "coinbase", "kraken"}


def test_taker_fee_at_least_maker_fee_for_every_venue():
    for schedule in VENUE_FEE_SCHEDULES.values():
        assert schedule.taker_fee_bps >= schedule.maker_fee_bps


def test_every_schedule_has_a_source_citation():
    for schedule in VENUE_FEE_SCHEDULES.values():
        assert schedule.source
        assert len(schedule.source) > 10


def test_binance_taker_fee_is_far_lower_than_the_other_two():
    # the real, verified finding this project's fee data surfaces: as of
    # 2026-08-06, Binance.US's base-tier taker fee (0.02%) is roughly
    # 30-40x lower than Coinbase's (0.60%) or Kraken's (0.80%) base tiers
    binance = VENUE_FEE_SCHEDULES["binance"].taker_fee_bps
    coinbase = VENUE_FEE_SCHEDULES["coinbase"].taker_fee_bps
    kraken = VENUE_FEE_SCHEDULES["kraken"].taker_fee_bps
    assert binance < coinbase / 10
    assert binance < kraken / 10
