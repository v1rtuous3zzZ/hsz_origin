"""在凌晨核对最近七个完整自然日，并只补不一致的源服务器窗口。"""

import argparse
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.etl.reconcile import reconcile


def main() -> None:
    parser = argparse.ArgumentParser(description="沪苏浙门架同步凌晨核对")
    parser.add_argument("--dry-run", action="store_true", help="仅输出待补窗口，不读取明细或写中心库")
    parser.add_argument("--max-repairs", type=int, default=24, help="单晚最多补同步窗口数")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    now = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    print(
        json.dumps(
            reconcile(now, max_repairs=args.max_repairs, execute=not args.dry_run),
            ensure_ascii=False,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
