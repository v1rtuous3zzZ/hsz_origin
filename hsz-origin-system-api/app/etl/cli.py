import argparse
import json
from datetime import datetime

from sqlalchemy import text

from app.db.session import SessionLocal
from app.etl.config import EtlSettings
from app.etl.job_queue import enqueue_job, get_job, run_worker
from app.etl.task_runner import (
    aligned_live_window,
    nightly_ranges,
)

settings = EtlSettings()


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def source_options(parser):
    parser.add_argument("--server")
    parser.add_argument("--source-mode", choices=("auto", "realtime", "history"), default="auto")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="沪苏浙门架单 worker ETL")
    sub = parser.add_subparsers(dest="command", required=True)
    once = sub.add_parser("live-once")
    source_options(once)
    once.add_argument("--start", type=parse_time)
    once.add_argument("--end", type=parse_time)
    once.add_argument("--force", action="store_true")
    live = sub.add_parser("live")
    source_options(live)
    live.add_argument("--poll-seconds", type=int, default=settings.poll_seconds)
    backfill = sub.add_parser("backfill")
    source_options(backfill)
    backfill.add_argument("--start", type=parse_time, required=True)
    backfill.add_argument("--end", type=parse_time, required=True)
    backfill.add_argument("--sleep-seconds", type=int, default=settings.history_sleep_seconds)
    backfill.add_argument("--force", "--no-resume", action="store_true", dest="force")
    backfill.add_argument("--stop-on-error", action="store_true")
    check = sub.add_parser("nightly-check")
    source_options(check)
    check.add_argument("--days", nargs="+", type=int, default=[1, 2])
    repair = sub.add_parser("repair")
    source_options(repair)
    repair.add_argument("--sync-id")
    repair.add_argument("--start", type=parse_time)
    repair.add_argument("--end", type=parse_time)
    status = sub.add_parser("job-status")
    status.add_argument("job_id", type=int)
    worker = sub.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    def enqueue(operation, start, end, **options):
        with SessionLocal.begin() as db:
            return enqueue_job(
                db, operation=operation, start=start, end=end,
                server_code=getattr(args, "server", None),
                source_mode=getattr(args, "source_mode", "auto"),
                **options,
            )

    if args.command == "live-once":
        start, end = (
            (args.start, args.end)
            if args.start and args.end
            else aligned_live_window(
                minutes=settings.live_window_minutes,
                safety_delay=settings.safety_delay,
            )
        )
        result = enqueue("LIVE", start, end, force=args.force, sleep_seconds=0)
    elif args.command == "live":
        last = None
        while True:
            window = aligned_live_window(
                minutes=settings.live_window_minutes,
                safety_delay=settings.safety_delay,
            )
            if window != last:
                result = enqueue("LIVE", *window, sleep_seconds=0)
                print(json.dumps(result, ensure_ascii=False, default=str))
                last = window
            __import__("time").sleep(args.poll_seconds)
    elif args.command == "backfill":
        result = enqueue(
            "BACKFILL", args.start, args.end, force=args.force,
            window_minutes=120, sleep_seconds=args.sleep_seconds,
            stop_on_error=args.stop_on_error,
        )
    elif args.command == "nightly-check":
        result = [enqueue("CHECK", start, end) for start, end in nightly_ranges(days=tuple(args.days))]
    elif args.command == "repair":
        if args.sync_id:
            with SessionLocal() as db:
                row = db.execute(text(
                    "SELECT server_code,window_start,window_end FROM t_etl_sync_log "
                    "WHERE sync_id=:id"
                ), {"id": args.sync_id}).mappings().one_or_none()
            if not row:
                parser.error("同步日志不存在")
            args.server = row["server_code"]
            result = enqueue("REPAIR", row["window_start"], row["window_end"], force=True)
        elif args.server and args.start and args.end:
            result = enqueue("REPAIR", args.start, args.end, force=True)
        else:
            parser.error("repair 需要 --sync-id，或同时提供 --server --start --end")
    elif args.command == "job-status":
        with SessionLocal() as db:
            result = get_job(db, args.job_id)
    else:
        result = run_worker(once=args.once)
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
