import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "progress.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS word_progress (
            word        TEXT PRIMARY KEY,
            level       TEXT NOT NULL DEFAULT 'pre-primer',
            correct     INTEGER NOT NULL DEFAULT 0,
            attempts    INTEGER NOT NULL DEFAULT 0,
            last_seen   TEXT,
            status      TEXT NOT NULL DEFAULT 'unseen'
        )
    """)
    conn.commit()
    conn.close()


def get_progress(word=None):
    conn = get_db()
    if word:
        row = conn.execute(
            "SELECT * FROM word_progress WHERE word = ?", (word.lower(),)
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    rows = conn.execute("SELECT * FROM word_progress ORDER BY word").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def record_attempt(word, correct: bool):
    conn = get_db()
    word = word.lower()
    row = conn.execute(
        "SELECT * FROM word_progress WHERE word = ?", (word,)
    ).fetchone()

    if row:
        new_correct = row["correct"] + (1 if correct else 0)
        new_attempts = row["attempts"] + 1
        # Determine status
        if new_correct / new_attempts >= 0.8 and new_attempts >= 3:
            status = "learned"
        elif new_correct / new_attempts < 0.5 and new_attempts >= 3:
            status = "needs_work"
        else:
            status = "learning"
        conn.execute(
            """UPDATE word_progress
               SET correct = ?, attempts = ?, last_seen = datetime('now'), status = ?
               WHERE word = ?""",
            (new_correct, new_attempts, status, word),
        )
    else:
        status = "learning"
        conn.execute(
            """INSERT INTO word_progress (word, correct, attempts, last_seen, status)
               VALUES (?, ?, 1, datetime('now'), ?)""",
            (word, 1 if correct else 0, status),
        )

    conn.commit()
    conn.close()
    return get_progress(word)


def set_word_level(word, level):
    conn = get_db()
    conn.execute(
        """INSERT INTO word_progress (word, level, correct, attempts, status)
           VALUES (?, ?, 0, 0, 'unseen')
           ON CONFLICT(word) DO UPDATE SET level = excluded.level""",
        (word.lower(), level),
    )
    conn.commit()
    conn.close()
