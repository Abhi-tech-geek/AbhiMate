import sqlite3
import json
import os
from typing import List, Dict, Any

class SQLiteDB:
    def __init__(self, db_path="database/abhimate.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                feature TEXT,
                state TEXT,
                timestamp REAL,
                data_json TEXT
            )
        ''')
        conn.commit()
        conn.close()

    def save_session(self, session_id: str, feature: str, state: str, timestamp: float, session_data: dict):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO sessions 
            (session_id, feature, state, timestamp, data_json)
            VALUES (?, ?, ?, ?, ?)
        ''', (session_id, feature, state, timestamp, json.dumps(session_data)))
        conn.commit()
        conn.close()

    def get_session(self, session_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT data_json FROM sessions WHERE session_id = ?', (session_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
        return None

    def delete_session(self, session_id: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM sessions WHERE session_id = ?', (session_id,))
        conn.commit()
        conn.close()

    def list_sessions(self) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT session_id, feature, state, timestamp FROM sessions ORDER BY timestamp DESC')
        rows = cursor.fetchall()
        conn.close()
        return [{"session_id": r[0], "feature": r[1], "state": r[2], "timestamp": r[3]} for r in rows]
