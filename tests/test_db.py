"""SQLite CRUD round-trip for database.db_core.SQLiteDB."""

from database.db_core import SQLiteDB


def test_save_and_get_session(tmp_db_path):
    db = SQLiteDB(db_path=tmp_db_path)
    payload = {"session_id": "s1", "feature": "Login", "extra": [1, 2, 3]}
    db.save_session("s1", "Login", "GENERATED", 1700000000.0, payload)

    fetched = db.get_session("s1")
    assert fetched == payload


def test_list_sessions_sorted_desc(tmp_db_path):
    db = SQLiteDB(db_path=tmp_db_path)
    db.save_session("a", "First", "GENERATED", 100.0, {"x": 1})
    db.save_session("b", "Second", "EXECUTED", 200.0, {"x": 2})
    db.save_session("c", "Third", "EXECUTED", 150.0, {"x": 3})

    rows = db.list_sessions()
    assert [r["session_id"] for r in rows] == ["b", "c", "a"]
    assert rows[0]["state"] == "EXECUTED"


def test_delete_session(tmp_db_path):
    db = SQLiteDB(db_path=tmp_db_path)
    db.save_session("s1", "f", "GENERATED", 1.0, {"a": 1})
    db.delete_session("s1")
    assert db.get_session("s1") is None


def test_replace_on_save(tmp_db_path):
    db = SQLiteDB(db_path=tmp_db_path)
    db.save_session("s1", "old", "GENERATED", 1.0, {"v": 1})
    db.save_session("s1", "new", "EXECUTED", 2.0, {"v": 2})

    fetched = db.get_session("s1")
    assert fetched == {"v": 2}
    rows = db.list_sessions()
    assert len(rows) == 1
    assert rows[0]["feature"] == "new"
