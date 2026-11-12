#!/usr/bin/env bash
# Public TimeSeventeen/Polymarket-v1 files cited by the paper's Polymarket appendix.
# No API key. CTF splits are about 5 GB; curl resumes a partial file.
set -euo pipefail
ROOT="outputs/strategy/hlz_cross_section/cache/step2/timeseventeen"
BASE="https://huggingface.co/datasets/TimeSeventeen/Polymarket-v1/resolve/main"
mkdir -p "$ROOT/CTF" "$ROOT/daily_aligned" "$ROOT/daily_aligned_multi"

fetch() {
  local rel="$1"
  local dest="$ROOT/$rel"
  mkdir -p "$(dirname "$dest")"
  if [[ -s "$dest" ]]; then
    echo "have $rel"
    return 0
  fi
  echo "GET $rel"
  if [[ -f "$dest.partial" ]]; then
    curl -fL --retry 5 --retry-delay 3 -C - -o "$dest.partial" "$BASE/$rel"
  else
    curl -fL --retry 5 --retry-delay 3 -o "$dest.partial" "$BASE/$rel"
  fi
  mv "$dest.partial" "$dest"
  echo "done $rel $(wc -c < "$dest") bytes"
}

fetch CTF/resolutions.parquet
fetch CTF/merges.parquet
fetch CTF/redemptions.parquet
fetch CTF/splits.parquet

days=$(python3 - << 'PY'
from datetime import date, timedelta
day = date(2024, 10, 23)
end = date(2024, 11, 6)
while day <= end:
    print(day.strftime("%Y_%m_%d"))
    day += timedelta(days=1)
PY
)
for day in $days; do
  fetch "daily_aligned/${day}.parquet" || echo "missing daily_aligned/${day}"
  fetch "daily_aligned_multi/${day}.parquet" || echo "missing daily_aligned_multi/${day}"
done
VG="outputs/strategy/hlz_cross_section/cache/step2/vgregoire"
VGBASE="https://huggingface.co/datasets/vgregoire/polymarket-users/resolve/main"
mkdir -p "$VG/ohlcv_1h"
if [[ ! -s "$VG/predictions.parquet" ]]; then
  echo "GET predictions.parquet"
  curl -fL --retry 5 --retry-delay 3 -o "$VG/predictions.parquet" "$VGBASE/predictions.parquet"
fi
if [[ ! -s "$VG/markets.parquet" ]]; then
  echo "GET markets.parquet"
  curl -fL --retry 5 --retry-delay 3 -o "$VG/markets.parquet" "$VGBASE/markets.parquet"
fi
# Pilot window above, then every hourly file the price sample can use.
# vgregoire hourly bars end 2026-03-29 (2026-03-30 is HTTP 404).
hourly_days=$(python3 - << 'PY'
from datetime import date, timedelta
day = date(2022, 11, 21)
end = date(2026, 3, 29)
while day <= end:
    print(day.strftime("%Y_%m_%d"))
    day += timedelta(days=1)
PY
)
for day in $hourly_days; do
  year=${day:0:4}
  month=${day:5:2}
  dom=${day:8:2}
  dest="$VG/ohlcv_1h/${day}.parquet"
  if [[ -s "$dest" ]]; then
    continue
  fi
  echo "GET ohlcv_1h/${day}"
  curl -fL --retry 5 --retry-delay 3 -o "$dest" \
    "$VGBASE/ohlcv_1h/year=${year}/month=${month}/day=${dom}/data.parquet" \
    || echo "missing ohlcv_1h/${day}"
done

echo DOWNLOAD_OK
