"""统一同步脚本。

示例：

    python scripts/run_sync.py live
    python scripts/run_sync.py live-once
    python scripts/run_sync.py backfill --start 2026-01-01T00:00:00 --end 2026-02-01T00:00:00
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.etl.cli import main  # noqa: E402


if __name__ == "__main__":
    main()
