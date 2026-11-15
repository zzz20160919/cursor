from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.strategies.pm_hl.clients import hyperliquid as hl  # noqa: E402
from src.strategies.pm_hl.clients import polymarket as pm  # noqa: E402


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def print_missing_env() -> None:
    pm_missing = pm.missing_env(("PM_PRIVATE_KEY",))
    hl_missing = hl.missing_env(("HL_AGENT_KEY",))
    if pm_missing:
        print(f"Missing optional PM secret(s): {', '.join(pm_missing)}")
        print("PM authenticated cash may be unavailable; public positions still attempted.")
    if hl_missing:
        print(f"Missing optional HL secret(s): {', '.join(hl_missing)}")
        print("HL read-only spot/perp balances do not require the agent key.")


def read_pm(dry_run: bool) -> float:
    funder = pm.get_funder()
    print(f"\nPOLYMARKET read-only ({funder})")
    total = 0.0
    if not dry_run and not pm.missing_env(("PM_PRIVATE_KEY", "PM_FUNDER")):
        try:
            client = pm.build_client()
            cash, _ = pm.get_cash(client)
            print(f"  authenticated cash: ${cash or 0:.2f}")
            total += cash or 0.0
        except Exception as exc:
            print(f"  authenticated cash read failed: {str(exc)[:120]}")
    else:
        print("  authenticated cash: skipped in dry-run or missing PM_PRIVATE_KEY")

    try:
        value = pm.get_value(funder)
        positions = pm.get_positions(funder)
        positions = positions if isinstance(positions, list) else []
        print(f"  public position value: ${value:.2f}")
        print(f"  open positions: {len(positions)}")
        for position in positions[:10]:
            title = str(position.get("title", position.get("asset", "?")))[:48]
            print(
                "    "
                f"{title:<48} size={position.get('size')} value={position.get('currentValue')}"
            )
        total += value
    except Exception as exc:
        print(f"  public positions read failed: {str(exc)[:120]}")

    return total


def hl_mark_coin(coin: str) -> str:
    if coin.startswith("+"):
        return "#" + coin[1:]
    return coin


def estimate_hl_outcome_value(coin: str, amount: float) -> float:
    book_coin = hl_mark_coin(coin)
    bids, _ = hl.coin_book(book_coin)
    bid = bids[0][0] if bids else 0.0
    return amount * bid


def read_hl() -> float:
    account = hl.get_account()
    print(f"\nHYPERLIQUID read-only ({account})")
    total = 0.0
    try:
        balances = hl.spot_balances(account)
        print("  spot balances:")
        for coin, amount in balances:
            if amount == 0:
                continue
            marker = " outcome_token" if coin.startswith(("#", "@", "+")) else ""
            if coin == "USDC":
                total += amount
                print(f"    {coin:<12} {amount:.6f}{marker}")
            elif coin.startswith(("#", "@", "+")):
                try:
                    value = estimate_hl_outcome_value(coin, amount)
                    total += value
                    print(f"    {coin:<12} {amount:.6f}{marker} est_value=${value:.2f}")
                except Exception as exc:
                    print(f"    {coin:<12} {amount:.6f}{marker} est_value=unavailable ({str(exc)[:60]})")
            else:
                print(f"    {coin:<12} {amount:.6f}{marker}")
    except Exception as exc:
        print(f"  spot balances read failed: {str(exc)[:120]}")

    try:
        account_value, positions = hl.perp_state(account)
        account_value_f = float(account_value or 0.0)
        print(f"  perp account value: ${account_value_f:.2f}")
        print(f"  perp positions: {len(positions or [])}")
        total += account_value_f
    except Exception as exc:
        print(f"  perp state read failed: {str(exc)[:120]}")

    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Read PM-HL positions without placing orders.")
    parser.add_argument("--dry-run", action="store_true", help="Do not build authenticated clients.")
    args = parser.parse_args()

    pm.load_env()
    hl.load_env()
    print(f"PM-HL position report {now_iso()}")
    print("Mode: read-only; no orders are placed.")
    print_missing_env()

    pm_total = read_pm(dry_run=args.dry_run)
    hl_total = read_hl()
    print("\nSUMMARY")
    print(f"  PM visible total: ${pm_total:.2f}")
    print(f"  HL visible total: ${hl_total:.2f}")
    print("  Note: HL outcome tokens are listed explicitly so they are not missed.")


if __name__ == "__main__":
    main()
