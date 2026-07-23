from app.etl.cli import build_parser


def test_backfill_uses_low_impact_history_defaults():
    args = build_parser().parse_args(
        [
            "backfill",
            "--start",
            "2026-01-01T00:00:00",
            "--end",
            "2026-02-01T00:00:00",
        ]
    )

    assert args.window_minutes == 120
    assert args.sleep_seconds == 10
    assert args.batch_size == 2000
    assert args.max_workers == 1
