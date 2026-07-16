from app.etl.normalizer import event_key


def test_event_key_is_stable_and_server_scoped():
    assert event_key(1, "trade") == event_key(1, "trade")
    assert event_key(1, "trade") != event_key(2, "trade")
