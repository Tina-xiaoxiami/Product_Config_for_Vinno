"""The phase-zero reader uses the current model visibility contract."""
import sqlite3

import pytest

from tracker.services.product_strategy import DOMESTIC_V10_SERIES, ProductStrategyReader


@pytest.mark.parametrize("has_enabled", [False, True])
def test_strategy_lists_and_resolves_only_current_models(tmp_path, has_enabled):
    path = tmp_path / "config.db"
    with sqlite3.connect(path) as connection:
        enabled_column = ", is_enabled INTEGER NOT NULL DEFAULT 1" if has_enabled else ""
        connection.executescript(
            "CREATE TABLE product_series(id INTEGER PRIMARY KEY, name TEXT);"
            f"CREATE TABLE product_models(id INTEGER PRIMARY KEY, series_id INTEGER, name TEXT, status TEXT{enabled_column});"
        )
        connection.execute("INSERT INTO product_series VALUES (1, ?)", (DOMESTIC_V10_SERIES,))
        connection.execute("INSERT INTO product_series VALUES (2, 'Tulip-China')")
        connection.executemany("INSERT INTO product_models(id,series_id,name,status) VALUES (?,?,?,?)", [
            (1, 1, "Current", None), (2, 1, "Retired alias", "已合并"),
            (3, 1, "Disabled", "生产中"), (4, 2, "Other series", None),
        ])
        if has_enabled:
            connection.execute("UPDATE product_models SET is_enabled=0 WHERE id=3")
    reader = ProductStrategyReader(path)
    expected = [1] if has_enabled else [1, 3]
    assert [row["id"] for row in reader.list_models()["models"]] == expected
    with reader._connect() as connection:
        assert reader._find_source_models(connection, ("Retired alias",)) == []
        assert reader._find_source_models(connection, ("Other series",)) == []
        if has_enabled:
            assert reader._find_source_models(connection, ("Disabled",)) == []
