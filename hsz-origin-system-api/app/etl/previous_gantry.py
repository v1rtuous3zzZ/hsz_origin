import re

FIELDS = ("last_gantry_hex_pass", "obu_last_gantry_hex", "last_gantry_hex", "fee_prov_begin_hex")
HEX = re.compile(r"^[0-9A-Fa-f]{6}$")


def select_previous_gantry(row: dict) -> tuple[str | None, str | None, dict[str, object]]:
    raw = {field: row.get(field) for field in FIELDS}
    for field in FIELDS:
        value = raw[field]
        if value and HEX.fullmatch(str(value).strip()):
            return str(value).strip().upper(), field, raw
    return None, None, raw
