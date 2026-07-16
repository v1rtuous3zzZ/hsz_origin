from app.etl.batch_log import finish_batch


class FakeSession:
    def __init__(self):
        self.parameters = None

    def execute(self, _statement, parameters):
        self.parameters = parameters


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
