from app.etl.models import Event, Rule


def match(event: Event, rules: list[Rule]) -> list[Rule]:
    if not event.success_flag:
        return []
    matched: dict[int, Rule] = {}
    for rule in rules:
        active = rule.valid_from <= event.event_time and (
            rule.valid_to is None or event.event_time < rule.valid_to
        )
        current = rule.current_gantry_hex == event.current_gantry_hex
        previous = (
            rule.rule_type == "CURRENT_ONLY"
            or rule.previous_gantry_hex == event.previous_gantry_hex
        )
        if active and current and previous:
            matched.setdefault(rule.object_no, rule)
    return list(matched.values())
