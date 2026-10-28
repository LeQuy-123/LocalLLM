"""Persistent memory: everything the companion learns about the user lives in one SQLite file.

Tables
  facts       durable knowledge about the user (name, likes, job, routines...), with confidence
  messages    raw conversation log
  episodes    summaries of past conversations (long-term recall)
  app_usage   which apps the user spends time in, by hour of day (habits)
  aliases     learned shortcuts, e.g. "my editor" -> "code", "work playlist" -> URL
  prefs       adaptive behaviour settings (chattiness, voice, screen watching...)
  feedback    reactions to proactive remarks, used to tune chattiness
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path

DEFAULT_PREFS = {
    "chattiness": 0.5,        # 0 = silent unless spoken to, 1 = comments on everything
    "screen_watch": True,
    "user_name": "",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.6,
    source TEXT,
    hits INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL,
    updated REAL NOT NULL,
    UNIQUE(category, key)
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    session INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY,
    ts_start REAL NOT NULL,
    ts_end REAL NOT NULL,
    summary TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_usage (
    app TEXT NOT NULL,
    hour INTEGER NOT NULL,
    seconds REAL NOT NULL DEFAULT 0,
    last_title TEXT,
    last_seen REAL,
    PRIMARY KEY (app, hour)
);
CREATE TABLE IF NOT EXISTS aliases (
    name TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0,
    updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS prefs (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    context TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS recall USING fts5(kind, ref, text);
"""


def _fts_query(text: str) -> str:
    words = [w for w in re.findall(r"[\w']{3,}", text.lower()) if w not in _STOP]
    return " OR ".join(f'"{w}"' for w in words[:12])


_STOP = set("the and you for are but not with this that have what your was can how about from just like will "
            "would could should there their them they then than when where which who why yes okay".split())


class Memory:
    def __init__(self, db_path: str | Path):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.db.executescript(SCHEMA)
            self.db.commit()
        self.session = self._next_session()

    # ---------- helpers ----------
    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    def _query(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def _next_session(self) -> int:
        row = self._query("SELECT MAX(session) AS s FROM messages")
        return (row[0]["s"] or 0) + 1

    # ---------- preferences (adaptive behaviour) ----------
    def get_pref(self, key: str):
        row = self._query("SELECT value FROM prefs WHERE key=?", (key,))
        if not row:
            return DEFAULT_PREFS.get(key)
        return json.loads(row[0]["value"])

    def set_pref(self, key: str, value) -> None:
        self._exec("INSERT INTO prefs(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, json.dumps(value)))

    def nudge_pref(self, key: str, delta: float, lo: float = 0.0, hi: float = 1.0) -> float:
        value = min(hi, max(lo, float(self.get_pref(key) or 0) + delta))
        self.set_pref(key, round(value, 3))
        return value

    # ---------- facts ----------
    def upsert_fact(self, category: str, key: str, value: str, confidence: float = 0.6, source: str = "chat") -> None:
        category, key, value = category.strip().lower(), key.strip().lower(), value.strip()
        if not key or not value:
            return
        now = time.time()
        existing = self._query("SELECT id, value, confidence FROM facts WHERE category=? AND key=?", (category, key))
        if existing:
            old = existing[0]
            # Repeating the same fact makes us more sure; a changed value replaces it.
            conf = min(1.0, old["confidence"] + 0.1) if old["value"].lower() == value.lower() else confidence
            self._exec("UPDATE facts SET value=?, confidence=?, source=?, updated=? WHERE id=?",
                       (value, conf, source, now, old["id"]))
            self._exec("DELETE FROM recall WHERE kind='fact' AND ref=?", (str(old["id"]),))
            fact_id = old["id"]
        else:
            cur = self._exec("INSERT INTO facts(category,key,value,confidence,source,created,updated) VALUES(?,?,?,?,?,?,?)",
                             (category, key, value, confidence, source, now, now))
            fact_id = cur.lastrowid
        self._exec("INSERT INTO recall(kind,ref,text) VALUES('fact',?,?)", (str(fact_id), f"{category} {key}: {value}"))
        if category == "identity" and key in ("name", "user_name", "preferred_name"):
            self.set_pref("user_name", value)

    def forget(self, text: str) -> int:
        rows = self._query("SELECT id FROM facts WHERE key LIKE ? OR value LIKE ?", (f"%{text}%", f"%{text}%"))
        for r in rows:
            self._exec("DELETE FROM facts WHERE id=?", (r["id"],))
            self._exec("DELETE FROM recall WHERE kind='fact' AND ref=?", (str(r["id"]),))
        return len(rows)

    def top_facts(self, limit: int = 30) -> list[sqlite3.Row]:
        return self._query("SELECT * FROM facts ORDER BY confidence * (1 + hits * 0.1) DESC, updated DESC LIMIT ?",
                           (limit,))

    def all_facts(self) -> list[dict]:
        return [dict(r) for r in self._query("SELECT category,key,value,confidence,updated FROM facts ORDER BY category,key")]

    # ---------- recall ----------
    def recall(self, text: str, limit: int = 6) -> list[str]:
        q = _fts_query(text)
        if not q:
            return []
        try:
            rows = self._query("SELECT kind, ref, text FROM recall WHERE recall MATCH ? ORDER BY rank LIMIT ?", (q, limit))
        except sqlite3.OperationalError:
            return []
        for r in rows:
            if r["kind"] == "fact":
                self._exec("UPDATE facts SET hits = hits + 1 WHERE id=?", (int(r["ref"]),))
        return [f"[{r['kind']}] {r['text']}" for r in rows]

    # ---------- conversation ----------
    def add_message(self, role: str, content: str) -> None:
        self._exec("INSERT INTO messages(ts,role,content,session) VALUES(?,?,?,?)",
                   (time.time(), role, content, self.session))

    def recent_messages(self, limit: int) -> list[dict]:
        rows = self._query("SELECT role, content FROM messages WHERE session=? ORDER BY id DESC LIMIT ?",
                           (self.session, limit))
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def session_messages(self) -> list[sqlite3.Row]:
        return self._query("SELECT ts, role, content FROM messages WHERE session=? ORDER BY id", (self.session,))

    def last_message_ts(self) -> float | None:
        row = self._query("SELECT MAX(ts) AS t FROM messages WHERE session=?", (self.session,))
        return row[0]["t"]

    def close_session(self, summary: str) -> None:
        msgs = self.session_messages()
        if msgs and summary:
            cur = self._exec("INSERT INTO episodes(ts_start,ts_end,summary) VALUES(?,?,?)",
                             (msgs[0]["ts"], msgs[-1]["ts"], summary))
            day = time.strftime("%Y-%m-%d", time.localtime(msgs[0]["ts"]))
            self._exec("INSERT INTO recall(kind,ref,text) VALUES('episode',?,?)", (str(cur.lastrowid), f"{day}: {summary}"))
        self.session += 1

    def recent_episodes(self, limit: int = 3) -> list[str]:
        rows = self._query("SELECT ts_start, summary FROM episodes ORDER BY id DESC LIMIT ?", (limit,))
        return [f"{time.strftime('%Y-%m-%d', time.localtime(r['ts_start']))}: {r['summary']}" for r in rows]

    # ---------- habits ----------
    def log_app_time(self, app: str, title: str, seconds: float) -> None:
        hour = time.localtime().tm_hour
        self._exec("""INSERT INTO app_usage(app,hour,seconds,last_title,last_seen) VALUES(?,?,?,?,?)
                      ON CONFLICT(app,hour) DO UPDATE SET seconds=seconds+excluded.seconds,
                      last_title=excluded.last_title, last_seen=excluded.last_seen""",
                   (app, hour, seconds, title[:200], time.time()))

    def habits_summary(self, limit: int = 6) -> str:
        rows = self._query("SELECT app, SUM(seconds) AS s FROM app_usage GROUP BY app ORDER BY s DESC LIMIT ?", (limit,))
        if not rows:
            return ""
        hour = time.localtime().tm_hour
        now_rows = self._query("SELECT app FROM app_usage WHERE hour=? ORDER BY seconds DESC LIMIT 3", (hour,))
        top = ", ".join(f"{r['app']} ({r['s'] / 3600:.1f}h)" for r in rows)
        usual = ", ".join(r["app"] for r in now_rows)
        return f"Most used apps overall: {top}." + (f" Usually at this hour: {usual}." if usual else "")

    # ---------- aliases (learned shortcuts) ----------
    def set_alias(self, name: str, kind: str, target: str) -> None:
        self._exec("""INSERT INTO aliases(name,kind,target,updated) VALUES(?,?,?,?)
                      ON CONFLICT(name) DO UPDATE SET kind=excluded.kind, target=excluded.target, updated=excluded.updated""",
                   (name.strip().lower(), kind, target, time.time()))

    def get_alias(self, name: str) -> sqlite3.Row | None:
        rows = self._query("SELECT * FROM aliases WHERE name=?", (name.strip().lower(),))
        if rows:
            self._exec("UPDATE aliases SET uses=uses+1 WHERE name=?", (rows[0]["name"],))
            return rows[0]
        return None

    def list_aliases(self) -> list[dict]:
        return [dict(r) for r in self._query("SELECT name, kind, target, uses FROM aliases ORDER BY uses DESC")]

    # ---------- feedback ----------
    def add_feedback(self, kind: str, context: str = "") -> None:
        self._exec("INSERT INTO feedback(ts,kind,context) VALUES(?,?,?)", (time.time(), kind, context[:500]))

    # ---------- prompt context ----------
    def profile_block(self) -> str:
        facts = self.top_facts()
        lines = [f"- ({f['category']}) {f['key']}: {f['value']}" for f in facts]
        parts = []
        if lines:
            parts.append("What you know about the user:\n" + "\n".join(lines))
        eps = self.recent_episodes()
        if eps:
            parts.append("Recent past conversations:\n" + "\n".join(f"- {e}" for e in eps))
        habits = self.habits_summary()
        if habits:
            parts.append("User habits: " + habits)
        aliases = self.list_aliases()[:15]
        if aliases:
            parts.append("Learned shortcuts: " + "; ".join(f"'{a['name']}' -> {a['kind']}:{a['target']}" for a in aliases))
        return "\n\n".join(parts)
