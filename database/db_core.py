"""SQLite persistence layer.

Phase C: adds a ``users`` table and a ``user_id`` column on ``sessions`` so
data is isolated per logged-in user. Includes a lightweight migration that
back-fills the new column on existing databases.
"""

import sqlite3
import json
import os
import time
from typing import List, Dict, Any, Optional


class SQLiteDB:
    def __init__(self, db_path: str = None):
        # In the cloud we point this at a mounted volume (e.g.
        # /app/data/abhimate.db via ABHIMATE_DB_PATH) so the DB survives
        # redeploys. Locally it falls back to the in-repo path.
        self.db_path = db_path or os.environ.get(
            "ABHIMATE_DB_PATH", "database/abhimate.db"
        )
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
        self._migrate()

    # ------------------------------------------------------------------
    # Schema bootstrap + migrations
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                feature TEXT,
                state TEXT,
                timestamp REAL,
                data_json TEXT
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                display_name TEXT,
                created_at REAL NOT NULL,
                last_login_at REAL
            )
        ''')
        # Phase #9 — self-healing locator cache. Key is per-host so localhost
        # vs prod don't share entries. Global (not user-scoped) because the
        # winning selector is a property of the page, not the user.
        cur.execute('''
            CREATE TABLE IF NOT EXISTS locator_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host TEXT NOT NULL,
                primary_by TEXT NOT NULL,
                primary_value TEXT NOT NULL,
                winning_by TEXT NOT NULL,
                winning_value TEXT NOT NULL,
                success_count INTEGER NOT NULL DEFAULT 1,
                last_used_at REAL NOT NULL,
                UNIQUE(host, primary_by, primary_value)
            )
        ''')
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_locator_cache_host "
            "ON locator_cache(host)"
        )
        # Phase #11 — bug-tracker credentials. Per-user, one row per provider.
        # NOTE: tokens are stored as-is. The intended use is a personal/local
        # dev box. For multi-tenant production we would Fernet-encrypt at rest.
        cur.execute('''
            CREATE TABLE IF NOT EXISTS ticket_credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                base_url TEXT,
                auth_email TEXT,
                auth_token TEXT,
                default_project TEXT,
                updated_at REAL NOT NULL,
                UNIQUE(user_id, provider)
            )
        ''')
        # Phase #7 — scheduled runs + Slack notifications.
        # Slack credentials are per-user (one webhook each). The schedules
        # table joins a (user, session_id) to a parsed expression and tracks
        # the next firing time so the scheduler thread can do a single
        # ``WHERE next_run_at <= now`` scan per tick.
        cur.execute('''
            CREATE TABLE IF NOT EXISTS slack_credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                webhook_url TEXT NOT NULL,
                default_channel TEXT,
                mention_on_fail TEXT,
                updated_at REAL NOT NULL
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                expression TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                slack_notify INTEGER NOT NULL DEFAULT 1,
                next_run_at REAL NOT NULL,
                last_run_at REAL,
                last_status TEXT,
                last_error TEXT,
                created_at REAL NOT NULL,
                UNIQUE(user_id, session_id)
            )
        ''')
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_schedules_due "
            "ON schedules(enabled, next_run_at)"
        )
        conn.commit()
        conn.close()

    def _migrate(self) -> None:
        """Idempotent: add user_id column to sessions if it's missing."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(sessions)")
        cols = {row[1] for row in cur.fetchall()}
        if "user_id" not in cols:
            cur.execute("ALTER TABLE sessions ADD COLUMN user_id INTEGER")
            conn.commit()
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, timestamp DESC)")
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # User CRUD
    # ------------------------------------------------------------------

    def create_user(self, email: str, password_hash: str, display_name: Optional[str] = None) -> int:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (email, password_hash, display_name, created_at) VALUES (?, ?, ?, ?)",
            (email, password_hash, display_name, time.time()),
        )
        uid = cur.lastrowid
        conn.commit()
        conn.close()
        return uid

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, email, password_hash, display_name, created_at, last_login_at "
            "FROM users WHERE email = ? COLLATE NOCASE",
            (email,),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "id": row[0], "email": row[1], "password_hash": row[2],
            "display_name": row[3], "created_at": row[4], "last_login_at": row[5],
        }

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, email, display_name, created_at, last_login_at FROM users WHERE id = ?",
            (user_id,),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "id": row[0], "email": row[1], "display_name": row[2],
            "created_at": row[3], "last_login_at": row[4],
        }

    def update_last_login(self, user_id: int) -> None:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (time.time(), user_id))
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # Session CRUD (user-scoped)
    # ------------------------------------------------------------------

    def save_session(
        self,
        session_id: str,
        feature: str,
        state: str,
        timestamp: float,
        session_data: dict,
        user_id: Optional[int] = None,
    ) -> None:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        # If row exists, preserve its user_id (so an update by a session-scoped
        # caller doesn't accidentally re-stamp ownership). We only set user_id
        # when creating a new row.
        cur.execute("SELECT user_id FROM sessions WHERE session_id = ?", (session_id,))
        existing = cur.fetchone()
        effective_uid = existing[0] if existing else user_id
        cur.execute(
            'INSERT OR REPLACE INTO sessions '
            '(session_id, feature, state, timestamp, data_json, user_id) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (session_id, feature, state, timestamp,
             json.dumps(session_data), effective_uid),
        )
        conn.commit()
        conn.close()

    def get_session(self, session_id: str) -> Optional[dict]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute('SELECT data_json FROM sessions WHERE session_id = ?', (session_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
        return None

    def get_session_owner(self, session_id: str) -> Optional[int]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute('SELECT user_id FROM sessions WHERE session_id = ?', (session_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return row[0]

    def delete_session(self, session_id: str) -> None:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute('DELETE FROM sessions WHERE session_id = ?', (session_id,))
        conn.commit()
        conn.close()

    def list_sessions(self, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        if user_id is None:
            cur.execute(
                'SELECT session_id, feature, state, timestamp, user_id '
                'FROM sessions ORDER BY timestamp DESC'
            )
        else:
            cur.execute(
                'SELECT session_id, feature, state, timestamp, user_id '
                'FROM sessions WHERE user_id = ? ORDER BY timestamp DESC',
                (user_id,),
            )
        rows = cur.fetchall()
        conn.close()
        return [{
            "session_id": r[0], "feature": r[1], "state": r[2],
            "timestamp": r[3], "user_id": r[4],
        } for r in rows]

    def count_user_sessions(self, user_id: int) -> int:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (user_id,))
        n = cur.fetchone()[0]
        conn.close()
        return int(n or 0)

    # ------------------------------------------------------------------
    # Self-healing locator cache (Phase #9)
    # ------------------------------------------------------------------

    def lookup_locator(self, host: str, primary_by: str, primary_value: str) -> Optional[dict]:
        """Return the cached winning locator for (host, primary). None if no entry."""
        if not host:
            return None
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT winning_by, winning_value, success_count, last_used_at "
            "FROM locator_cache "
            "WHERE host = ? AND primary_by = ? AND primary_value = ?",
            (host, primary_by, primary_value),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "winning_by": row[0],
            "winning_value": row[1],
            "success_count": int(row[2] or 0),
            "last_used_at": float(row[3] or 0),
        }

    def record_locator(
        self,
        host: str,
        primary_by: str,
        primary_value: str,
        winning_by: str,
        winning_value: str,
    ) -> None:
        """Persist a successful fallback resolution.

        - First time we see this primary -> insert with count=1
        - Same winning locator as before -> bump success_count
        - Different winning locator (DOM shifted again) -> overwrite + reset count
        """
        if not host:
            return
        now = time.time()
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT winning_by, winning_value FROM locator_cache "
            "WHERE host = ? AND primary_by = ? AND primary_value = ?",
            (host, primary_by, primary_value),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO locator_cache "
                "(host, primary_by, primary_value, winning_by, winning_value, success_count, last_used_at) "
                "VALUES (?, ?, ?, ?, ?, 1, ?)",
                (host, primary_by, primary_value, winning_by, winning_value, now),
            )
        elif row[0] == winning_by and row[1] == winning_value:
            cur.execute(
                "UPDATE locator_cache SET success_count = success_count + 1, last_used_at = ? "
                "WHERE host = ? AND primary_by = ? AND primary_value = ?",
                (now, host, primary_by, primary_value),
            )
        else:
            cur.execute(
                "UPDATE locator_cache SET winning_by = ?, winning_value = ?, "
                "success_count = 1, last_used_at = ? "
                "WHERE host = ? AND primary_by = ? AND primary_value = ?",
                (winning_by, winning_value, now, host, primary_by, primary_value),
            )
        conn.commit()
        conn.close()

    def list_locator_cache(self, host: Optional[str] = None, limit: int = 200) -> List[dict]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        if host:
            cur.execute(
                "SELECT host, primary_by, primary_value, winning_by, winning_value, "
                "success_count, last_used_at FROM locator_cache "
                "WHERE host = ? ORDER BY last_used_at DESC LIMIT ?",
                (host, limit),
            )
        else:
            cur.execute(
                "SELECT host, primary_by, primary_value, winning_by, winning_value, "
                "success_count, last_used_at FROM locator_cache "
                "ORDER BY last_used_at DESC LIMIT ?",
                (limit,),
            )
        rows = cur.fetchall()
        conn.close()
        return [{
            "host": r[0],
            "primary_by": r[1], "primary_value": r[2],
            "winning_by": r[3], "winning_value": r[4],
            "success_count": int(r[5] or 0),
            "last_used_at": float(r[6] or 0),
        } for r in rows]

    def clear_locator_cache(self, host: Optional[str] = None) -> int:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        if host:
            cur.execute("DELETE FROM locator_cache WHERE host = ?", (host,))
        else:
            cur.execute("DELETE FROM locator_cache")
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        return int(deleted or 0)

    # ------------------------------------------------------------------
    # Bug-tracker credentials (Phase #11)
    # ------------------------------------------------------------------

    def set_ticket_credentials(
        self,
        user_id: int,
        provider: str,
        base_url: Optional[str] = None,
        auth_email: Optional[str] = None,
        auth_token: Optional[str] = None,
        default_project: Optional[str] = None,
    ) -> None:
        """Upsert credentials for (user, provider). Use empty/None values
        to clear individual fields."""
        if not user_id or not provider:
            raise ValueError("user_id and provider are required")
        provider = provider.lower().strip()
        if provider not in {"jira", "linear"}:
            raise ValueError(f"unknown provider: {provider}")
        now = time.time()
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO ticket_credentials "
            "(user_id, provider, base_url, auth_email, auth_token, default_project, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, provider) DO UPDATE SET "
            "  base_url = excluded.base_url, "
            "  auth_email = excluded.auth_email, "
            "  auth_token = excluded.auth_token, "
            "  default_project = excluded.default_project, "
            "  updated_at = excluded.updated_at",
            (user_id, provider, base_url, auth_email, auth_token, default_project, now),
        )
        conn.commit()
        conn.close()

    def get_ticket_credentials(self, user_id: int, provider: str) -> Optional[dict]:
        """Returns the full row (incl. token) for use by the provider adapter."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT provider, base_url, auth_email, auth_token, default_project, updated_at "
            "FROM ticket_credentials WHERE user_id = ? AND provider = ?",
            (user_id, provider.lower().strip()),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "provider": row[0], "base_url": row[1], "auth_email": row[2],
            "auth_token": row[3], "default_project": row[4],
            "updated_at": float(row[5] or 0),
        }

    def list_ticket_credentials(self, user_id: int) -> List[dict]:
        """Public list — masks the token. For UI display only."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT provider, base_url, auth_email, auth_token, default_project, updated_at "
            "FROM ticket_credentials WHERE user_id = ? ORDER BY provider",
            (user_id,),
        )
        rows = cur.fetchall()
        conn.close()
        out = []
        for r in rows:
            tok = r[3] or ""
            mask = f"{tok[:4]}…{tok[-4:]}" if len(tok) > 8 else "(set)"
            out.append({
                "provider": r[0],
                "base_url": r[1],
                "auth_email": r[2],
                "token_mask": mask if tok else "",
                "default_project": r[4],
                "updated_at": float(r[5] or 0),
            })
        return out

    def delete_ticket_credentials(self, user_id: int, provider: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM ticket_credentials WHERE user_id = ? AND provider = ?",
            (user_id, provider.lower().strip()),
        )
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        return bool(deleted)

    # ------------------------------------------------------------------
    # Slack credentials (Phase #7)
    # ------------------------------------------------------------------

    def set_slack_credentials(
        self,
        user_id: int,
        webhook_url: str,
        default_channel: Optional[str] = None,
        mention_on_fail: Optional[str] = None,
    ) -> None:
        """Upsert the user's Slack webhook. The URL must be a Slack incoming
        webhook (``https://hooks.slack.com/services/...``)."""
        if not user_id:
            raise ValueError("user_id is required")
        webhook_url = (webhook_url or "").strip()
        if not webhook_url.startswith("https://hooks.slack.com/"):
            raise ValueError(
                "webhook_url must be a Slack incoming webhook "
                "(https://hooks.slack.com/services/…)"
            )
        now = time.time()
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO slack_credentials "
            "(user_id, webhook_url, default_channel, mention_on_fail, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "  webhook_url = excluded.webhook_url, "
            "  default_channel = excluded.default_channel, "
            "  mention_on_fail = excluded.mention_on_fail, "
            "  updated_at = excluded.updated_at",
            (user_id, webhook_url, default_channel, mention_on_fail, now),
        )
        conn.commit()
        conn.close()

    def get_slack_credentials(self, user_id: int) -> Optional[dict]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT webhook_url, default_channel, mention_on_fail, updated_at "
            "FROM slack_credentials WHERE user_id = ?",
            (user_id,),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "webhook_url": row[0],
            "default_channel": row[1],
            "mention_on_fail": row[2],
            "updated_at": float(row[3] or 0),
        }

    def get_slack_credentials_public(self, user_id: int) -> Optional[dict]:
        """Same as ``get_slack_credentials`` but masks the webhook secret —
        safe to ship to the UI."""
        row = self.get_slack_credentials(user_id)
        if not row:
            return None
        url = row["webhook_url"] or ""
        # Slack webhook layout: https://hooks.slack.com/services/T.../B.../<secret>
        # Mask the trailing secret only — the team + bot id are fine to show.
        masked = url
        try:
            head, sep, tail = url.rpartition("/")
            if sep and tail:
                masked = head + "/" + (tail[:4] + "…" + tail[-4:] if len(tail) > 8 else "***")
        except Exception:
            pass
        return {
            "webhook_mask": masked,
            "default_channel": row["default_channel"],
            "mention_on_fail": row["mention_on_fail"],
            "updated_at": row["updated_at"],
        }

    def delete_slack_credentials(self, user_id: int) -> bool:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("DELETE FROM slack_credentials WHERE user_id = ?", (user_id,))
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        return bool(deleted)

    # ------------------------------------------------------------------
    # Schedules (Phase #7)
    # ------------------------------------------------------------------

    def upsert_schedule(
        self,
        user_id: int,
        session_id: str,
        expression: str,
        next_run_at: float,
        enabled: bool = True,
        slack_notify: bool = True,
    ) -> int:
        """Create or update the schedule for (user, session). Returns the row id."""
        if not user_id or not session_id:
            raise ValueError("user_id and session_id are required")
        now = time.time()
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO schedules "
            "(user_id, session_id, expression, enabled, slack_notify, "
            " next_run_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, session_id) DO UPDATE SET "
            "  expression = excluded.expression, "
            "  enabled = excluded.enabled, "
            "  slack_notify = excluded.slack_notify, "
            "  next_run_at = excluded.next_run_at",
            (user_id, session_id, expression, int(bool(enabled)),
             int(bool(slack_notify)), float(next_run_at), now),
        )
        conn.commit()
        cur.execute(
            "SELECT id FROM schedules WHERE user_id = ? AND session_id = ?",
            (user_id, session_id),
        )
        rid = cur.fetchone()[0]
        conn.close()
        return int(rid)

    def list_schedules(self, user_id: int) -> List[dict]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, session_id, expression, enabled, slack_notify, "
            "       next_run_at, last_run_at, last_status, last_error, created_at "
            "FROM schedules WHERE user_id = ? ORDER BY next_run_at ASC",
            (user_id,),
        )
        rows = cur.fetchall()
        conn.close()
        return [{
            "id": r[0], "session_id": r[1], "expression": r[2],
            "enabled": bool(r[3]), "slack_notify": bool(r[4]),
            "next_run_at": float(r[5] or 0),
            "last_run_at": float(r[6] or 0) if r[6] else None,
            "last_status": r[7], "last_error": r[8],
            "created_at": float(r[9] or 0),
        } for r in rows]

    def get_schedule(self, schedule_id: int, user_id: Optional[int] = None) -> Optional[dict]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        if user_id is not None:
            cur.execute(
                "SELECT id, user_id, session_id, expression, enabled, slack_notify, "
                "       next_run_at, last_run_at, last_status, last_error "
                "FROM schedules WHERE id = ? AND user_id = ?",
                (schedule_id, user_id),
            )
        else:
            cur.execute(
                "SELECT id, user_id, session_id, expression, enabled, slack_notify, "
                "       next_run_at, last_run_at, last_status, last_error "
                "FROM schedules WHERE id = ?",
                (schedule_id,),
            )
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "id": row[0], "user_id": row[1], "session_id": row[2],
            "expression": row[3], "enabled": bool(row[4]),
            "slack_notify": bool(row[5]),
            "next_run_at": float(row[6] or 0),
            "last_run_at": float(row[7] or 0) if row[7] else None,
            "last_status": row[8], "last_error": row[9],
        }

    def delete_schedule(self, schedule_id: int, user_id: int) -> bool:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM schedules WHERE id = ? AND user_id = ?",
            (schedule_id, user_id),
        )
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        return bool(deleted)

    def set_schedule_enabled(self, schedule_id: int, user_id: int, enabled: bool) -> bool:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "UPDATE schedules SET enabled = ? WHERE id = ? AND user_id = ?",
            (int(bool(enabled)), schedule_id, user_id),
        )
        updated = cur.rowcount
        conn.commit()
        conn.close()
        return bool(updated)

    def claim_due_schedules(self, now: float) -> List[dict]:
        """Atomically pick (and push the next_run_at far enough into the future
        to avoid double-firing) every enabled schedule whose ``next_run_at``
        has passed. The caller is responsible for computing and writing the
        real next_run_at after the run finishes.

        The temporary push (``now + 3600``) gives the executor up to an hour
        to complete one run before the same row could come due again if the
        caller crashes before re-arming.
        """
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, user_id, session_id, expression, slack_notify "
            "FROM schedules WHERE enabled = 1 AND next_run_at <= ?",
            (now,),
        )
        rows = cur.fetchall()
        if rows:
            ids = [r[0] for r in rows]
            placeholders = ",".join("?" for _ in ids)
            cur.execute(
                f"UPDATE schedules SET next_run_at = ? WHERE id IN ({placeholders})",
                [now + 3600, *ids],
            )
            conn.commit()
        conn.close()
        return [{
            "id": r[0], "user_id": r[1], "session_id": r[2],
            "expression": r[3], "slack_notify": bool(r[4]),
        } for r in rows]

    def finalize_schedule_run(
        self,
        schedule_id: int,
        next_run_at: float,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        """Write the real next_run_at + last-run telemetry after a fire."""
        now = time.time()
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "UPDATE schedules SET next_run_at = ?, last_run_at = ?, "
            "last_status = ?, last_error = ? WHERE id = ?",
            (float(next_run_at), now, status, error, schedule_id),
        )
        conn.commit()
        conn.close()
