from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest

from app.etl.models import SourceServer
from app.etl.source_reader import SourceQueryIndexError, source_connection, validate_query_index


def make_source(port: int = 3307, database: str = "gantry_a") -> SourceServer:
    return SourceServer(1, "source-a", "10.13.0.1", port, database, "current", None, "key")


@pytest.mark.parametrize(
    ("port", "database"), [(3307, "gantry_a"), (3310, "gantry_b")]
)
def test_source_connection_uses_each_server_port_and_database(port, database) -> None:
    result = MagicMock()
    result.mappings.return_value.all.return_value = [
        {"port": 3306, "username": "reader", "password": "secret", "db_name": "common", "charset": "utf8mb4"}
    ]
    center = MagicMock()
    center.execute.return_value = result
    remote = MagicMock()
    with (
        patch("app.etl.source_reader.engine.connect", return_value=nullcontext(center)),
        patch("app.etl.source_reader.pymysql.connect", return_value=remote) as connect,
    ):
        source_connection(make_source(port, database))

    assert connect.call_args.kwargs["port"] == port
    assert connect.call_args.kwargs["database"] == database


def test_source_connection_prefers_credential_key_environment() -> None:
    remote = MagicMock()
    with (
        patch("app.etl.source_reader.source_credentials", return_value=("key-user", "key-pass")),
        patch("app.etl.source_reader.engine.connect") as center,
        patch("app.etl.source_reader.pymysql.connect", return_value=remote) as connect,
    ):
        source_connection(make_source())

    center.assert_not_called()
    assert connect.call_args.kwargs["user"] == "key-user"
    assert connect.call_args.kwargs["password"] == "key-pass"


def test_query_index_accepts_gantry_time_prefix() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {"Key_name": "idx_query", "Seq_in_index": 1, "Column_name": "GantryId"},
        {"Key_name": "idx_query", "Seq_in_index": 2, "Column_name": "TransTime"},
        {"Key_name": "idx_query", "Seq_in_index": 3, "Column_name": "TradeId"},
    ]
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor

    assert validate_query_index(
        connection,
        make_source(),
        "history_202601",
        {"gantry_id": "GantryId", "trans_time": "TransTime"},
        required=True,
    )
    cursor.execute.assert_called_once_with("SHOW INDEX FROM `history_202601`")


def test_history_query_rejects_missing_composite_index() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {"Key_name": "idx_time", "Seq_in_index": 1, "Column_name": "TransTime"}
    ]
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor

    with pytest.raises(SourceQueryIndexError, match="复合索引"):
        validate_query_index(
            connection,
            make_source(),
            "history_202602",
            {"gantry_id": "GantryId", "trans_time": "TransTime"},
            required=True,
        )
