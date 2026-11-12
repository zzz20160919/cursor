from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from src.strategies.btc_nq_weekend.event_dataset import (  # noqa: E402
    DEFAULT_BTC_LOOKBACKS,
    DEFAULT_NQ_FORWARDS,
    build_event_dataset,
    write_event_dataset,
)


DEFAULT_BTC_INPUT = (
    Path("D:/cursor/202604_stra")
    / "data/market_data/binance/futures/um/klines/BTCUSDT/1m/btcusdt_um_1m_2020_2026.parquet"
)
DEFAULT_NQ_INPUT = (
    Path("D:/cursor/202604_stra")
    / "data/market_data/databento/GLBX.MDP3/NQ/1m/nq_continuous_volume_front_1m_2020_2026.parquet"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "data/strategy/btc_nq_weekend/event_dataset.csv"


def parse_csv_list(value: str) -> tuple[str, ...]:
    items = tuple(item.strip() for item in value.split(",") if item.strip())
    if not items:
        raise argparse.ArgumentTypeError("list cannot be empty")
    return items


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build BTC-NQ weekend event-study dataset. This is not a production backtest."
    )
    parser.add_argument("--btc-input", type=Path, default=DEFAULT_BTC_INPUT, help="BTC CSV/parquet input path.")
    parser.add_argument("--nq-input", type=Path, default=DEFAULT_NQ_INPUT, help="NQ CSV/parquet input path.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output .csv or .parquet event dataset.")
    parser.add_argument("--start", default=None, help="Inclusive UTC start timestamp/date.")
    parser.add_argument("--end", default=None, help="Inclusive UTC end timestamp/date.")
    parser.add_argument(
        "--event-names",
        type=parse_csv_list,
        default=("monday_0930", "sunday_1700"),
        help="Comma-separated event grids, e.g. monday_0930,sunday_1700.",
    )
    parser.add_argument(
        "--btc-lookbacks",
        type=parse_csv_list,
        default=DEFAULT_BTC_LOOKBACKS,
        help="Comma-separated BTC lookbacks.",
    )
    parser.add_argument(
        "--nq-forwards",
        type=parse_csv_list,
        default=DEFAULT_NQ_FORWARDS,
        help="Comma-separated NQ forward windows.",
    )
    parser.add_argument(
        "--btc-bar-freq",
        default="1m",
        help="BTC endpoint floor frequency. Use 1h to emulate old BTC 1h CSV endpoint keys.",
    )
    parser.add_argument("--cost-rate", type=float, default=0.001, help="Fixed event cost for primary pair net return.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    frame = build_event_dataset(
        btc_input=args.btc_input,
        nq_input=args.nq_input,
        start=args.start,
        end=args.end,
        event_names=args.event_names,
        btc_lookbacks=args.btc_lookbacks,
        nq_forwards=args.nq_forwards,
        btc_bar_freq=args.btc_bar_freq,
        cost_rate=args.cost_rate,
    )
    write_event_dataset(frame, args.output)
    counts = frame.groupby("event_name").size().to_dict() if not frame.empty else {}
    primary = frame.loc[
        (frame["event_name"] == "monday_0930") & frame["btc_feature_ok"] & frame["nq_target_ok"]
    ]
    print(f"Wrote event dataset: {args.output}")
    print(f"Rows: {len(frame)}")
    print(f"Event row counts: {counts}")
    print(f"Primary monday_0930 usable rows: {len(primary)}")
    print("No production backtest was run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

