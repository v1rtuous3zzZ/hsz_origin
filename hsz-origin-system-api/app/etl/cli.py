import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from app.db.session import SessionLocal
from app.etl.config import EtlSettings
from app.etl.formal_sync import sync_window
from app.etl.job_queue import get_manual_job, run_manual_worker
from app.etl.orchestrator import (
    rebuild_fact_range,
    run_live_loop,
    run_live_once,
    sync_range,
)
from app.etl.source_config import load_mapping, load_sources

settings = EtlSettings()


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def configure_logging() -> None:
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler("logs/etl.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def add_common_source_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--server", help="只同步指定 server_code")
    parser.add_argument("--batch-size", type=int, help="门架流式读取批次")
    parser.add_argument("--max-workers", type=int, help="不同门架服务器最大并发数")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="沪苏浙 G50 ETL 独立进程")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect", help="查看启用的源服务器和门架映射")
    add_common_source_options(inspect)

    status = sub.add_parser("status", help="查看最近同步批次")
    status.add_argument("--job-code")
    status.add_argument("--limit", type=int, default=20)

    job = sub.add_parser("job-status", help="查看手动同步后台任务")
    job.add_argument("job_id", type=int)

    once = sub.add_parser("live-once", help="同步最近一个完整两小时窗口")
    add_common_source_options(once)
    once.add_argument("--start", type=parse_time, help="可选：显式窗口开始")
    once.add_argument("--end", type=parse_time, help="可选：显式窗口结束")
    once.add_argument("--force", action="store_true", help="即使已有成功记录也重新同步")

    live = sub.add_parser("live", help="常驻循环执行两小时同步")
    add_common_source_options(live)
    live.add_argument("--poll-seconds", type=int)
    live.add_argument("--max-cycles", type=int, help="测试用；省略则持续运行")

    backfill = sub.add_parser("backfill", help="按窗口循环补历史数据")
    add_common_source_options(backfill)
    backfill.add_argument("--start", type=parse_time, required=True)
    backfill.add_argument("--end", type=parse_time, required=True)
    backfill.add_argument(
        "--window-minutes", type=int, default=settings.history_window_minutes
    )
    backfill.set_defaults(
        batch_size=settings.history_source_batch_size,
        max_workers=settings.history_max_workers,
    )
    backfill.add_argument(
        "--sleep-seconds", type=int, default=settings.history_sleep_seconds
    )
    backfill.add_argument("--no-resume", action="store_true", help="不跳过已成功窗口")
    backfill.add_argument("--stop-on-error", action="store_true")
    backfill.add_argument("--skip-fact-rebuild", action="store_true")
    backfill.add_argument("--max-windows", type=int)

    facts = sub.add_parser("rebuild-facts", help="只在中心库重建指定区间事实")
    facts.add_argument("--start", type=parse_time, required=True)
    facts.add_argument("--end", type=parse_time, required=True)

    worker = sub.add_parser("worker", help="持续消费 HTTP 手动同步任务")
    worker.add_argument("--poll-seconds", type=int)
    worker.add_argument("--once", action="store_true", help="最多处理一个任务后退出")
    worker.add_argument("--max-jobs", type=int, help="处理指定数量任务后退出")

    return parser


def main() -> None:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "inspect":
        with SessionLocal() as db:
            sources, mapping = load_sources(db, args.server), load_mapping(db)
        result = {
            "enabled_sources": len(sources),
            "physical_gantries": sum(map(len, mapping.values())),
            "servers": [
                {
                    "server_code": source.server_code,
                    "physical_gantries": list(mapping.get(source.source_server_id, {})),
                }
                for source in sources
            ],
        }
    elif args.command == "status":
        with SessionLocal() as db:
            result = [
                dict(row)
                for row in db.execute(
                    text(
                        "SELECT batch_no,job_code,status,window_start,window_end,"
                        "source_row_count,success_event_count,matched_event_count,error_summary "
                        "FROM t_etl_batch WHERE (:job IS NULL OR job_code=:job) "
                        "ORDER BY batch_id DESC LIMIT :limit"
                    ),
                    {"job": args.job_code, "limit": args.limit},
                ).mappings()
            ]
    elif args.command == "job-status":
        with SessionLocal() as db:
            result = get_manual_job(db, args.job_id)
        if result is None:
            parser.error("手动同步任务不存在")
    elif args.command == "live-once":
        if (args.start is None) != (args.end is None):
            parser.error("--start 与 --end 必须同时提供")
        if args.start is not None:
            result = sync_window(
                args.start,
                args.end,
                args.server,
                rebuild_facts=True,
                job_code="LIVE_SYNC",
                job_type="INCREMENTAL",
                source_batch_size=args.batch_size,
                max_workers=args.max_workers,
                skip_successful_sources=not args.force,
            )
        else:
            result = run_live_once(
                server_code=args.server,
                resume=not args.force,
                source_batch_size=args.batch_size,
                max_workers=args.max_workers,
            )
    elif args.command == "live":
        result = run_live_loop(
            poll_seconds=args.poll_seconds,
            server_code=args.server,
            max_cycles=args.max_cycles,
            source_batch_size=args.batch_size,
            max_workers=args.max_workers,
        )
    elif args.command == "backfill":
        result = sync_range(
            args.start,
            args.end,
            server_code=args.server,
            window_minutes=args.window_minutes,
            sleep_seconds=args.sleep_seconds,
            resume=not args.no_resume,
            continue_on_error=not args.stop_on_error,
            rebuild_facts=not args.skip_fact_rebuild,
            max_windows=args.max_windows,
            source_batch_size=args.batch_size,
            max_workers=args.max_workers,
        )
    elif args.command == "rebuild-facts":
        result = rebuild_fact_range(args.start, args.end)
    elif args.command == "worker":
        result = run_manual_worker(
            poll_seconds=args.poll_seconds,
            once=args.once,
            max_jobs=args.max_jobs,
        )
    else:
        parser.error("未知命令")

    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
