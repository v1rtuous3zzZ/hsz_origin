from app.etl.locks import lock_name


def test_live_and_backfill_locks_differ():
    assert lock_name("live") != lock_name("backfill", job_name="legacy")


def test_same_job_has_same_lock():
    assert lock_name("backfill", job_name="legacy") == lock_name("backfill", job_name="legacy")
