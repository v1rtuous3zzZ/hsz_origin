import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

from app.db.session import SessionLocal
from app.etl.formal_sync import sync_window
from app.etl.runner import windows
from app.etl.source_config import load_mapping, load_sources


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def add_window_arguments(parser):
    parser.add_argument("--source-mode", choices=["legacy-test", "remote"], required=True)
    parser.add_argument("--server")
    parser.add_argument("--start", type=parse_time)
    parser.add_argument("--end", type=parse_time)


def main():
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler("logs/etl.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    parser = argparse.ArgumentParser(description="沪苏浙 G50 ETL 独立进程")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--source-mode", choices=["legacy-test", "remote"], required=True)
    inspect.add_argument("--server")
    inspect.add_argument("--month")
    once = sub.add_parser("live-once")
    add_window_arguments(once)
    backfill = sub.add_parser("backfill")
    add_window_arguments(backfill)
    backfill.add_argument("--window-minutes", type=int, default=60)
    backfill.add_argument("--job-name", required=True)
    backfill.add_argument("--batch-size", type=int)
    backfill.add_argument("--max-workers", type=int)
    backfill.add_argument("--sleep-seconds", type=int)
    backfill.add_argument("--reset-checkpoint", action="store_true")
    backfill.add_argument("--skip-fact-rebuild", action="store_true")
    live = sub.add_parser("live")
    add_window_arguments(live)
    live.add_argument("--poll-seconds", type=int, default=60)
    live.add_argument("--allow-legacy-live", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("--job-code")
    status.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    with SessionLocal() as db:
        if args.command == "inspect":
            sources, mapping = load_sources(db, args.server), load_mapping(db)
            print(
                json.dumps(
                    {
                        "enabled_sources": len(sources),
                        "physical_gantries": sum(map(len, mapping.values())),
                        "servers": [
                            {
                                "server_code": s.server_code,
                                "physical_gantries": list(mapping.get(s.source_server_id, {})),
                            }
                            for s in sources
                        ],
                    },
                    ensure_ascii=False,
                    default=str,
                )
            )
            return
        if args.command == "status":
            from sqlalchemy import text

            print(
                json.dumps(
                    [
                        dict(r)
                        for r in db.execute(
                            text(
                                "SELECT batch_no,job_code,status,window_start,window_end,error_summary FROM t_etl_batch WHERE (:job IS NULL OR job_code=:job) ORDER BY batch_id DESC LIMIT :limit"
                            ),
                            {"job": args.job_code, "limit": args.limit},
                        ).mappings()
                    ],
                    ensure_ascii=False,
                    default=str,
                )
            )
            return
        if not args.start or not args.end:
            parser.error("--start 与 --end 在本阶段验证中必填")
        if (
            args.command == "live"
            and args.source_mode == "legacy-test"
            and not args.allow_legacy_live
        ):
            parser.error("legacy-test live 需要 --allow-legacy-live")
        if args.source_mode != "remote":
            parser.error("正式同步仅支持 remote 源服务器")
        if args.command == "backfill":
            result = [
                sync_window(start, end, args.server, rebuild_facts=not args.skip_fact_rebuild)
                for start, end in windows(args.start, args.end, args.window_minutes)
            ]
        else:
            result = sync_window(args.start, args.end, args.server)
        print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
