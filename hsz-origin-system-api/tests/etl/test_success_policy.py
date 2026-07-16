from app.etl.success_policy import is_success


def test_media_specific_uses_only_the_confirmed_success_field():
    assert is_success({"media_type": "1", "obu_trade_result": 0, "trade_result": 9}, "MEDIA_SPECIFIC") == (True, "MEDIA_SPECIFIC")
    assert is_success({"media_type": "2", "obu_trade_result": 0, "trade_result": 9}, "MEDIA_SPECIFIC") == (False, "MEDIA_SPECIFIC")
    assert is_success({"media_type": "3", "obu_trade_result": 0, "trade_result": 0}, "MEDIA_SPECIFIC") == (False, "MEDIA_SPECIFIC")
