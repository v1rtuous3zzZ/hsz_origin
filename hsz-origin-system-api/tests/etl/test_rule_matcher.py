from datetime import datetime

from app.etl.models import Event, Rule
from app.etl.rule_matcher import match


def event(previous="AAAAAA"):
    return Event(
        b"x" * 32,
        1,
        "t",
        "id",
        datetime(2026, 1, 1),
        "p",
        "BBBBBB",
        previous,
        None,
        "{}",
        None,
        None,
        None,
        None,
        None,
        True,
        "TEST",
    )


def rule(no, obj, kind, previous=None):
    return Rule(no, obj, kind, previous, "BBBBBB", datetime(2020, 1, 1), None)


def test_matches_current_and_previous_without_duplicate_object():
    assert [
        r.object_no
        for r in match(
            event(),
            [
                rule(1, 110, "CURRENT_ONLY"),
                rule(2, 110, "PREVIOUS_TO_CURRENT", "AAAAAA"),
                rule(3, 111, "PREVIOUS_TO_CURRENT", "AAAAAA"),
            ],
        )
    ] == [110, 111]
