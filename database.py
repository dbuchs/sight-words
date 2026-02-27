import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "progress.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()

    # Create students table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    """)

    # Ensure a default student exists so student_id=1 always resolves
    conn.execute("INSERT OR IGNORE INTO students (id, name) VALUES (1, 'Default')")

    # Migrate word_progress if it has the legacy single-column primary key.
    # We detect this by checking whether 'student_id' is already a column.
    existing_cols = [
        r[1] for r in conn.execute("PRAGMA table_info(word_progress)").fetchall()
    ]
    if existing_cols and "student_id" not in existing_cols:
        # Rename legacy table, create new schema, copy data, drop legacy.
        conn.execute("ALTER TABLE word_progress RENAME TO word_progress_legacy")
        existing_cols = []  # force CREATE TABLE below

    if not existing_cols:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS word_progress (
                student_id  INTEGER NOT NULL DEFAULT 1,
                word        TEXT NOT NULL,
                level       TEXT NOT NULL DEFAULT 'pre-primer',
                correct     INTEGER NOT NULL DEFAULT 0,
                attempts    INTEGER NOT NULL DEFAULT 0,
                last_seen   TEXT,
                status      TEXT NOT NULL DEFAULT 'unseen',
                PRIMARY KEY (student_id, word),
                FOREIGN KEY (student_id) REFERENCES students(id)
            )
        """)
        # Copy legacy rows if they exist
        legacy = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='word_progress_legacy'"
        ).fetchone()
        if legacy:
            conn.execute("""
                INSERT INTO word_progress (student_id, word, level, correct, attempts, last_seen, status)
                SELECT 1, word, level, correct, attempts, last_seen, status
                FROM word_progress_legacy
            """)
            conn.execute("DROP TABLE word_progress_legacy")
    else:
        # Table already has the new schema
        conn.execute("""
            CREATE TABLE IF NOT EXISTS word_progress (
                student_id  INTEGER NOT NULL DEFAULT 1,
                word        TEXT NOT NULL,
                level       TEXT NOT NULL DEFAULT 'pre-primer',
                correct     INTEGER NOT NULL DEFAULT 0,
                attempts    INTEGER NOT NULL DEFAULT 0,
                last_seen   TEXT,
                status      TEXT NOT NULL DEFAULT 'unseen',
                PRIMARY KEY (student_id, word),
                FOREIGN KEY (student_id) REFERENCES students(id)
            )
        """)

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Student helpers
# ---------------------------------------------------------------------------

def create_student(name: str) -> dict:
    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO students (name) VALUES (?)", (name.strip(),))
    conn.commit()
    row = conn.execute("SELECT * FROM students WHERE name = ?", (name.strip(),)).fetchone()
    conn.close()
    return dict(row)


def get_students() -> list:
    conn = get_db()
    rows = conn.execute("SELECT * FROM students ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_student(student_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Progress helpers
# ---------------------------------------------------------------------------

def get_progress(word=None, student_id: int = 1):
    conn = get_db()
    if word:
        row = conn.execute(
            "SELECT * FROM word_progress WHERE student_id = ? AND word = ?",
            (student_id, word.lower()),
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    rows = conn.execute(
        "SELECT * FROM word_progress WHERE student_id = ? ORDER BY word",
        (student_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def record_attempt(word, correct: bool, student_id: int = 1):
    conn = get_db()
    word = word.lower()
    row = conn.execute(
        "SELECT * FROM word_progress WHERE student_id = ? AND word = ?",
        (student_id, word),
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
               WHERE student_id = ? AND word = ?""",
            (new_correct, new_attempts, status, student_id, word),
        )
    else:
        status = "learning"
        conn.execute(
            """INSERT INTO word_progress (student_id, word, correct, attempts, last_seen, status)
               VALUES (?, ?, ?, 1, datetime('now'), ?)""",
            (student_id, word, 1 if correct else 0, status),
        )

    conn.commit()
    conn.close()
    return get_progress(word, student_id=student_id)


def set_word_level(word, level, student_id: int = 1):
    conn = get_db()
    conn.execute(
        """INSERT INTO word_progress (student_id, word, level, correct, attempts, status)
           VALUES (?, ?, ?, 0, 0, 'unseen')
           ON CONFLICT(student_id, word) DO UPDATE SET level = excluded.level""",
        (student_id, word.lower(), level),
    )
    conn.commit()
    conn.close()
