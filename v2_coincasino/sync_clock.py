"""
Shared timing utility for all v2 scrapers.

sleep_until_next_tick(interval) sleeps until the next wall-clock tick
aligned to *interval* seconds, regardless of how long the current poll
cycle took.

Example
-------
    while True:
        do_work()                        # may take 0.3 s or 2.8 s
        sleep_until_next_tick(2.0)       # always wakes on 2-second boundaries
"""

import time


def sleep_until_next_tick(interval: float) -> None:
    """Sleep until the next aligned tick of *interval* seconds.

    If the current cycle completed in less than *interval* seconds, the
    function sleeps for the remaining time.  If the cycle overran, it
    sleeps until the next boundary so cycles never stack up.

    Parameters
    ----------
    interval:
        Poll interval in seconds (e.g. 2.0, 5.0).
    """
    now = time.monotonic()
    next_tick = (now // interval + 1) * interval
    sleep_for = max(0.0, next_tick - now)
    time.sleep(sleep_for)
