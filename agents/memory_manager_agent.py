from utils.models import TestSession
from database.db_core import SQLiteDB
from typing import List

class MemoryManagerAgent:
    def __init__(self):
        self.db = SQLiteDB()

    def save_session(self, session: TestSession):
        print(f"-> MemoryManager: Saving session {session.session_id}")
        self.db.save_session(
            session_id=session.session_id,
            feature=session.feature,
            state=session.state,
            timestamp=session.timestamp,
            session_data=session.model_dump()
        )

    def load_session(self, session_id: str) -> TestSession:
        print(f"-> MemoryManager: Loading session {session_id}")
        data = self.db.get_session(session_id)
        if not data:
            raise ValueError(f"Session {session_id} not found in DB.")
        return TestSession(**data)

    def list_all_sessions(self) -> List[dict]:
        return self.db.list_sessions()

    def delete_session(self, session_id: str):
        print(f"-> MemoryManager: Deleting session {session_id}")
        self.db.delete_session(session_id)
