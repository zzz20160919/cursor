from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "pm_hl_mvp2_scanner"

GAMMA_API = "https://gamma-api.polymarket.com"
GAMMA_PAGE_SIZE = 100
DEFAULT_GAMMA_PAGES = 20

PM_VENUE = "polymarket"
HL_VENUE = "hyperliquid"
HL_TAKER_FEE_DEFAULT = 0.0

