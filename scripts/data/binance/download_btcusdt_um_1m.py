from __future__ import annotations

import argparse
import io
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SYMBOL = "BTCUSDT"
DEFAULT_INTERVAL = "1m"
DEFAULT_START = "2020-01-01"
DEFAULT_END = "2026-04-01"
DEFAULT_START_MONTH = "2020-01"
DEFAULT_END_MONTH = "2026-04"
MONTHLY_BASE_URL = "https://data.binance.vision/data/futures/um/monthly/klines"
DAILY_BASE_URL = "https://data.binance.vision/data/futures/um/daily/klines"

KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base_asset_volume",
    "taker_buy_quote_asset_volume",
    "ignore",
]
NUMERIC_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_asset_volume",
    "taker_buy_base_asset_volume",
    "taker_buy_quote_asset_volume",
]


@dataclass(frozen=True, slots=True)
class DownloadResult:
    period: str
    status: str
    url: str
    path: Path
    notes: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Binance Vision USD-M BTCUSDT perpetual 1m klines and build a clean parquet."
    )
    parser.add_argument(
        "--mode",
        choices=("monthly", "daily"),
        default="monthly",
        help="Binance Vision ZIP granularity: monthly (default) or daily.",
    )
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--start", default=DEFAULT_START, help="Inclusive UTC start date/timestamp.")
    parser.add_argument("--end", default=DEFAULT_END, help="Exclusive UTC end date/timestamp.")
    parser.add_argument("--start-month", default=DEFAULT_START_MONTH, help="YYYY-MM")
    parser.add_argument("--end-month", default=DEFAULT_END_MONTH, help="YYYY-MM")
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=None,
        help="Local ZIP cache path. Default depends on --mode.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "market_data"
        / "binance"
        / "futures"
        / "um"
        / "klines"
        / DEFAULT_SYMBOL
        / DEFAULT_INTERVAL
        / "btcusdt_um_1m_2020_2026.parquet",
    )
    parser.add_argument("--delay-seconds", type=float, default=0.2)
    return parser.parse_args()


def month_range(start_month: str, end_month: str) -> list[str]:
    return [str(month) for month in pd.period_range(start=start_month, end=end_month, freq="M")]


def parse_utc(value: str) -> pd.Timestamp:
    return pd.Timestamp(pd.to_datetime(value, utc=True))


def month_range_for_dates(start: str, end: str) -> list[str]:
    start_ts = parse_utc(start)
    end_ts = parse_utc(end)
    if end_ts <= start_ts:
        raise ValueError("--end must be after --start")
    end_inclusive = end_ts - pd.Timedelta(nanoseconds=1)
    return month_range(start_ts.strftime("%Y-%m"), end_inclusive.strftime("%Y-%m"))


def day_range_for_dates(start: str, end: str) -> list[str]:
    start_ts = parse_utc(start)
    end_ts = parse_utc(end)
    if end_ts <= start_ts:
        raise ValueError("--end must be after --start")
    end_inclusive = end_ts - pd.Timedelta(nanoseconds=1)
    return [ts.strftime("%Y-%m-%d") for ts in pd.date_range(start=start_ts.normalize(), end=end_inclusive.normalize(), freq="D")]


def default_raw_dir(mode: str, symbol: str, interval: str) -> Path:
    granularity = "daily" if mode == "daily" else "monthly"
    return (
        PROJECT_ROOT
        / "data"
        / "raw"
        / "market_data"
        / "binance"
        / "futures"
        / "um"
        / granularity
        / "klines"
        / symbol
        / interval
    )


def clip_to_date_range(frame: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    start_ts = parse_utc(start)
    end_ts = parse_utc(end)
    return frame.loc[(frame["open_time_utc"] >= start_ts) & (frame["open_time_utc"] < end_ts)].reset_index(drop=True)


def download_zip(
    symbol: str,
    interval: str,
    period: str,
    raw_dir: Path,
    delay_seconds: float,
    *,
    mode: str,
) -> DownloadResult:
    raw_dir.mkdir(parents=True, exist_ok=True)
    base_url = DAILY_BASE_URL if mode == "daily" else MONTHLY_BASE_URL
    name = f"{symbol}-{interval}-{period}.zip"
    url = f"{base_url}/{symbol}/{interval}/{name}"
    path = raw_dir / name

    if path.exists() and path.stat().st_size > 0:
        return DownloadResult(period, "skipped_existing", url, path, "Local ZIP exists.")

    response = requests.get(url, timeout=60)
    time.sleep(delay_seconds)
    if response.status_code == 404:
        return DownloadResult(period, "missing_404", url, path, "HTTP 404.")
    if response.status_code != 200:
        return DownloadResult(period, "failed", url, path, f"HTTP {response.status_code}: {response.text[:200]}")
    if not response.content:
        return DownloadResult(period, "failed", url, path, "Empty response body.")

    path.write_bytes(response.content)
    return DownloadResult(period, "downloaded", url, path, f"Downloaded {len(response.content)} bytes.")


def download_month(symbol: str, interval: str, month: str, raw_dir: Path, delay_seconds: float) -> DownloadResult:
    return download_zip(symbol, interval, month, raw_dir, delay_seconds, mode="monthly")


def download_day(symbol: str, interval: str, day: str, raw_dir: Path, delay_seconds: float) -> DownloadResult:
    return download_zip(symbol, interval, day, raw_dir, delay_seconds, mode="daily")


def read_kline_zip(path: Path, period: str, source_column: str) -> pd.DataFrame:
    with zipfile.ZipFile(path) as archive:
        csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if not csv_names:
            raise ValueError(f"No CSV file found in {path}")
        with archive.open(csv_names[0]) as raw_file:
            content = raw_file.read()

    first_line = content.splitlines()[0].decode("utf-8", errors="ignore").lower()
    has_header = "open_time" in first_line or "open time" in first_line
    frame = pd.read_csv(io.BytesIO(content), header=0 if has_header else None, names=None if has_header else KLINE_COLUMNS)
    if has_header:
        frame.columns = KLINE_COLUMNS[: len(frame.columns)]
    frame = frame[KLINE_COLUMNS].copy()
    frame[source_column] = period
    return frame


def read_month_zip(path: Path, month: str) -> pd.DataFrame:
    return read_kline_zip(path, month, "source_month")


def read_day_zip(path: Path, day: str) -> pd.DataFrame:
    return read_kline_zip(path, day, "source_date")


def clean_klines(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["open_time"] = pd.to_numeric(out["open_time"], errors="coerce").astype("Int64")
    out["close_time"] = pd.to_numeric(out["close_time"], errors="coerce").astype("Int64")
    for column in NUMERIC_COLUMNS:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out["number_of_trades"] = pd.to_numeric(out["number_of_trades"], errors="coerce").astype("Int64")
    out["open_time_utc"] = pd.to_datetime(out["open_time"], unit="ms", utc=True, errors="coerce")
    out["close_time_utc"] = pd.to_datetime(out["close_time"], unit="ms", utc=True, errors="coerce")
    out = out.dropna(subset=["open_time", "close_time", "open_time_utc", "close_time_utc"])
    out = out.sort_values("open_time", kind="mergesort").drop_duplicates("open_time", keep="first")
    return out.reset_index(drop=True)


def summarize_daily_results(results: list[DownloadResult]) -> tuple[list[str], list[str], list[str]]:
    downloaded = [r.period for r in results if r.status in {"downloaded", "skipped_existing"}]
    unavailable = [r.period for r in results if r.status == "missing_404"]
    failed = [r.period for r in results if r.status == "failed"]
    return downloaded, unavailable, failed


def validate_daily_coverage(results: list[DownloadResult], days: list[str]) -> None:
    if not days:
        return
    required_days = days[:-1] if len(days) > 1 else days
    result_by_day = {result.period: result for result in results}
    missing_required = [
        day
        for day in required_days
        if result_by_day.get(day) is None or result_by_day[day].status not in {"downloaded", "skipped_existing"}
    ]
    if missing_required:
        raise RuntimeError(f"Required daily ZIPs missing or failed: {missing_required}")
    if len(days) > 1:
        optional_day = days[-1]
        optional_result = result_by_day.get(optional_day)
        if optional_result and optional_result.status == "failed":
            raise RuntimeError(f"Optional trailing daily ZIP failed: {optional_day} ({optional_result.notes})")


def run_monthly(args: argparse.Namespace, symbol: str, interval: str) -> int:
    if args.start != DEFAULT_START or args.end != DEFAULT_END:
        months = month_range_for_dates(args.start, args.end)
    else:
        months = month_range(args.start_month, args.end_month)

    results = [download_month(symbol, interval, month, args.raw_dir, args.delay_seconds) for month in months]
    frames: list[pd.DataFrame] = []
    read_failures: list[str] = []
    for result in results:
        if result.status not in {"downloaded", "skipped_existing"}:
            continue
        try:
            frames.append(read_month_zip(result.path, result.period))
        except Exception as exc:
            read_failures.append(f"{result.period}: {exc}")

    if not frames:
        print("No usable Binance monthly ZIP files were available.")
        for result in results:
            print(f"{result.period}: {result.status} - {result.notes}")
        return 1

    cleaned = clip_to_date_range(clean_klines(pd.concat(frames, ignore_index=True)), args.start, args.end)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cleaned.to_parquet(args.output, index=False)

    print(f"mode: monthly")
    print(f"output: {args.output}")
    print(f"rows: {len(cleaned)}")
    print(f"first_open_time_utc: {cleaned['open_time_utc'].min()}")
    print(f"last_open_time_utc: {cleaned['open_time_utc'].max()}")
    print(f"missing_or_failed_months: {[r.period for r in results if r.status in {'missing_404', 'failed'}]}")
    if read_failures:
        print(f"read_failures: {read_failures}")
    return 0


def run_daily(args: argparse.Namespace, symbol: str, interval: str) -> int:
    days = day_range_for_dates(args.start, args.end)
    results = [download_day(symbol, interval, day, args.raw_dir, args.delay_seconds) for day in days]
    downloaded_days, unavailable_days, failed_days = summarize_daily_results(results)

    for result in results:
        print(f"{result.period}: {result.status} - {result.notes}")

    if failed_days:
        print(f"failed_days: {failed_days}")
        return 1

    try:
        validate_daily_coverage(results, days)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    frames: list[pd.DataFrame] = []
    read_failures: list[str] = []
    for result in results:
        if result.status not in {"downloaded", "skipped_existing"}:
            continue
        try:
            frames.append(read_day_zip(result.path, result.period))
        except Exception as exc:
            read_failures.append(f"{result.period}: {exc}")

    if not frames:
        print("No usable Binance daily ZIP files were available.")
        print(f"unavailable_days: {unavailable_days}")
        return 1

    cleaned = clip_to_date_range(clean_klines(pd.concat(frames, ignore_index=True)), args.start, args.end)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cleaned.to_parquet(args.output, index=False)

    print(f"mode: daily")
    print(f"downloaded_days: {downloaded_days}")
    print(f"unavailable_days: {unavailable_days}")
    print(f"output: {args.output}")
    print(f"rows: {len(cleaned)}")
    print(f"first_open_time_utc: {cleaned['open_time_utc'].min()}")
    print(f"last_open_time_utc: {cleaned['open_time_utc'].max()}")
    if read_failures:
        print(f"read_failures: {read_failures}")
        return 1
    return 0


def main() -> int:
    args = parse_args()
    symbol = args.symbol.upper()
    interval = args.interval
    if args.raw_dir is None:
        args.raw_dir = default_raw_dir(args.mode, symbol, interval)

    if args.mode == "daily":
        return run_daily(args, symbol, interval)
    return run_monthly(args, symbol, interval)


if __name__ == "__main__":
    raise SystemExit(main())
