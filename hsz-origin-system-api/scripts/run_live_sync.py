"""兼容原 systemd timer：同步最近一个完整两小时窗口。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json

from app.etl.orchestrator import run_live_once  # noqa: E402


if __name__ == "__main__":
    print(json.dumps(run_live_once(), ensure_ascii=False, default=str))
