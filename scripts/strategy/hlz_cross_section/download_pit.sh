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
echo DOWNLOAD_OK
