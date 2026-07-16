REQUIRED = ("trade_id", "trans_time", "gantry_id")
ALIASES = {
    "trade_id": ("tradeid", "trade_id"),
    "trans_time": ("transtime", "trans_time"),
    "gantry_id": ("gantryid", "gantry_id"),
    "vehicle_plate": ("vehicleplate", "vehicle_plate"),
    "vehicle_type": ("vehicletype", "vehicle_type"),
    "pass_media_type": ("passmediatype", "pass_media_type"),
    "media_type": ("mediatype", "media_type"),
    "last_gantry_hex": ("lastgantryhex", "last_gantry_hex"),
    "last_gantry_hex_pass": ("lastgantryhexpass", "last_gantry_hex_pass"),
    "obu_last_gantry_hex": ("obulastgantryhex", "obu_last_gantry_hex"),
    "fee_prov_begin_hex": ("feeprovbeginhex", "fee_prov_begin_hex"),
    "en_toll_hex": ("entollstationhex", "en_toll_station_hex", "en_toll_hex"),
    "en_time": ("entime", "en_time"),
    "trade_result": ("traderesult", "trade_result"),
    "obu_trade_result": ("obutraderesult", "obu_trade_result"),
}


def resolve_columns(columns: list[str]) -> dict[str, str]:
    normalized = {column.lower().replace("_", ""): column for column in columns}
    resolved = {
        name: next(
            (normalized[a.replace("_", "")] for a in aliases if a.replace("_", "") in normalized),
            None,
        )
        for name, aliases in ALIASES.items()
    }
    missing = [name for name in REQUIRED if not resolved[name]]
    if missing:
        raise ValueError("源表缺少必需字段：" + "、".join(missing))
    return {name: column for name, column in resolved.items() if column}


def monthly_table(pattern: str | None, when) -> str | None:
    return pattern.replace("{yyyyMM}", when.strftime("%Y%m")) if pattern else None
