from app.etl.batch_log import finish_batch, start_batch


class FakeSession:
    def __init__(self):
        self.parameters = None

    def execute(self, _statement, parameters):
        self.parameters = parameters


class BatchSession:
    def __init__(self):
        self.statement = None
        self.parameters = None

    def execute(self, statement, parameters):
        self.statement = str(statement)
        self.parameters = parameters
        return type("Result", (), {"lastrowid": 7})()


def test_finish_batch_supplies_all_required_metrics():
    db = FakeSession()

    finish_batch(db, 7, "FAILED", {"source_row_count": 3}, "source read failed")

    assert db.parameters == {
        "id": 7,
        "status": "FAILED",
        "error": "source read failed",
        "source_row_count": 3,
        "success_event_count": 0,
        "matched_event_count": 0,
        "error_count": 0,
    }


def test_start_batch_uses_a_deterministic_two_hour_window_number():
    db = BatchSession()

    from datetime import datetime

    batch_id, batch_no = start_batch(
        db,
        "HISTORY_SYNC",
        "BACKFILL",
        datetime(2026, 7, 1, 8),
        datetime(2026, 7, 1, 10),
    )

    assert (batch_id, batch_no) == (7, "SYNC-202607010800-202607011000")
    assert "ON DUPLICATE KEY UPDATE" in db.statement
