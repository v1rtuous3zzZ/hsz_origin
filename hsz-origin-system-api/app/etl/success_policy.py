def is_success(row: dict, policy: str) -> tuple[bool, str]:
    if policy == "ALL_ROWS_TEST":
        return True, policy
    trade, obu = row.get("trade_result"), row.get("obu_trade_result")
    if policy == "TRADE_RESULT_ZERO":
        return str(trade) == "0", policy
    if policy == "ANY_RESULT_ZERO":
        return str(trade) == "0" or str(obu) == "0", policy
    if policy == "MEDIA_SPECIFIC":
        media_type = str(row.get("media_type"))
        if media_type == "1":
            return str(obu) == "0", policy
        if media_type == "2":
            return str(trade) == "0", policy
        return False, policy
    raise ValueError(f"未知成功交易策略：{policy}")
