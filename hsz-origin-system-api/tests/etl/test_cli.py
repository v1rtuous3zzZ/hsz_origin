from app.etl.cli import build_parser


def test_backfill_uses_two_hour_history_windows():
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
    assert args.sleep_seconds is None
