from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.db import P0_TABLES, connect, init_db  # noqa: E402


def main() -> None:
    db_path = init_db()
    with connect(db_path) as conn:
        tables = ", ".join(P0_TABLES)
        print(f"Initialized SQLite database: {db_path}")
        print(f"P0 tables ready: {tables}")


if __name__ == "__main__":
    main()
