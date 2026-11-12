from __future__ import annotations

import math


HALFLIFE_SEC = 4 * 3600
WARMUP_SEC = 1800
MIN_SAMPLES = 30


def ewma_stats(
    spreads: list[float],
    dt_sec: int,
) -> tuple[list[float | None], float | None, float | None, int]:
    n = len(spreads)
    if n == 0:
        return [], None, None, 0

    alpha = 1 - 0.5 ** (dt_sec / HALFLIFE_SEC)
    mean = spreads[0]
    var = 0.0
    covered = 0.0
    zs: list[float | None] = [None]

    for i in range(1, n):
        value = spreads[i]
        diff = value - mean
        sd = math.sqrt(var) if var > 0 else 0.0
        ready = covered >= WARMUP_SEC and (i + 1) >= MIN_SAMPLES and sd > 0
        zs.append((diff / sd) if ready else None)

        incr = alpha * diff
        mean += incr
        var = (1 - alpha) * (var + diff * incr)
        covered += dt_sec

    sd = math.sqrt(var) if var > 0 else 0.0
    return zs, mean, sd, n


def latest_z(spreads: list[float], dt_sec: int) -> tuple[float | None, float | None, float | None]:
    zs, mean, sd, _ = ewma_stats(spreads, dt_sec)
    return (zs[-1] if zs else None), mean, sd
