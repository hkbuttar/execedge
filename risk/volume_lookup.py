"""Real historical volume, looked up for an arbitrary sub-bar time window
-- what participation-rate limiting (participation_limit.py) checks child
order sizes against.

Disclosed simplification: `data.fetch_volume`'s real data is hourly bars
(or whatever --interval it was fetched with), but child orders are sliced
at much finer intervals (seconds to minutes). There's no real sub-hour
volume in this project's data pipeline to check against directly, so
`volume_between` prorates each overlapping bar's real volume by the
fraction of that bar's duration the query window covers, assuming volume
is spread uniformly within the bar. That's an assumption, not a
measurement -- real intra-bar volume is very unlikely to be perfectly
uniform (the time-of-day findings, `data/time_of_day.py`, are evidence
real volume is *not* uniform across hours, let alone necessarily uniform
within one).
Treat participation estimates from this as directionally right, not
precise to the second.
"""

from datetime import datetime, timedelta

import pandas as pd


class HistoricalVolumeLookup:
    def __init__(self, volume_df: pd.DataFrame, bar_seconds: int):
        self.bar_seconds = bar_seconds
        self._df = volume_df.sort_values("open_time").reset_index(drop=True)

    def volume_between(self, start: datetime, end: datetime) -> float:
        """Real volume estimated to have occurred in [start, end), prorated
        from whichever real bars overlap that window. Returns 0.0 if the
        window falls entirely outside the fetched history (not an error --
        callers should decide what "no data" means for their own use, e.g.
        a participation limiter treating unknown volume as zero rather
        than unlimited)."""
        if end <= start:
            return 0.0

        total = 0.0
        for row in self._df.itertuples(index=False):
            bar_start = row.open_time
            bar_end = bar_start + timedelta(seconds=self.bar_seconds)

            overlap_start = max(start, bar_start)
            overlap_end = min(end, bar_end)
            overlap_seconds = (overlap_end - overlap_start).total_seconds()
            if overlap_seconds <= 0:
                continue

            fraction = overlap_seconds / self.bar_seconds
            total += row.volume * fraction

        return total
