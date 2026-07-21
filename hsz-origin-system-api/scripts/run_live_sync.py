"""执行最近一个完整两小时窗口。"""

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "live-once"]
    runpy.run_module("app.etl.cli", run_name="__main__")
