"""User-scoped session persistence facade over SQLiteDB.

All operations carry an optional ``user_id`` so the same instance serves both
authenticated routes (scoped) and infrastructure paths (unscoped).
"""

from utils.models import TestSession
from database.db_core import SQLiteDB
from typing import List, Optional


SESSION_QUOTA_PER_USER = 5


class QuotaExceeded(Exception):
    """Raised when a user tries to exceed the session quota."""


class NotOwner(Exception):
    """Raised when a user touches a session they don't own."""


class MemoryManagerAgent:
    def __init__(self):
        self.db = SQLiteDB()

    # ------------------------------------------------------------------
    # Save / load / delete (with optional user scoping)
    # ------------------------------------------------------------------

    def save_session(self, session: TestSession, user_id: Optional[int] = None) -> None:
        """Persist a session. Enforces the per-user quota on *new* sessions.

        If ``user_id`` is provided and the session is brand new (not already in
        the DB), the user's session count must be below the quota.
        """
        if user_id is not None:
            existing_owner = self.db.get_session_owner(session.session_id)
            is_new = existing_owner is None and self.db.get_session(session.session_id) is None
            if is_new:
                if self.db.count_user_sessions(user_id) >= SESSION_QUOTA_PER_USER:
                    raise QuotaExceeded(
                        f"Session limit reached ({SESSION_QUOTA_PER_USER}). "
                        "Delete an existing session before creating a new one."
                    )
            elif existing_owner is not None and existing_owner != user_id:
                # User trying to overwrite someone else's session — block.
                raise NotOwner("You can only modify your own sessions.")

        print(f"-> MemoryManager: Saving session {session.session_id} (user={user_id})")
        self.db.save_session(
            session_id=session.session_id,
            feature=session.feature,
            state=session.state,
            timestamp=session.timestamp,
            session_data=session.model_dump(),
            user_id=user_id,
        )

    def load_session(self, session_id: str, user_id: Optional[int] = None) -> TestSession:
        data = self.db.get_session(session_id)
        if not data:
            raise ValueError(f"Session {session_id} not found in DB.")
        if user_id is not None:
            owner = self.db.get_session_owner(session_id)
            if owner is not None and owner != user_id:
                raise NotOwner("You cannot access another user's session.")
        return TestSession(**data)

    def list_all_sessions(self, user_id: Optional[int] = None) -> List[dict]:
        return self.db.list_sessions(user_id=user_id)

    def delete_session(self, session_id: str, user_id: Optional[int] = None) -> None:
        if user_id is not None:
            owner = self.db.get_session_owner(session_id)
            if owner is not None and owner != user_id:
                raise NotOwner("You cannot delete another user's session.")
        print(f"-> MemoryManager: Deleting session {session_id}")
        self.db.delete_session(session_id)

    # ------------------------------------------------------------------
    # Quota helpers
    # ------------------------------------------------------------------

    def quota_info(self, user_id: int) -> dict:
        used = self.db.count_user_sessions(user_id)
        return {
            "used": used,
            "limit": SESSION_QUOTA_PER_USER,
            "remaining": max(0, SESSION_QUOTA_PER_USER - used),
            "at_limit": used >= SESSION_QUOTA_PER_USER,
        }
