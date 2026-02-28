import sqlite3
import os

DB_PATH = os.environ.get("DB_PATH", "/data/progress.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()

    # Create students table (with optional PIN)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            pin  TEXT
        )
    """)

    # Migrate: add pin column if it doesn't exist yet
    student_cols = [r[1] for r in conn.execute("PRAGMA table_info(students)").fetchall()]
    if "pin" not in student_cols:
        conn.execute("ALTER TABLE students ADD COLUMN pin TEXT")

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
                next_review TEXT,
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
        # Table already has the new schema — ensure next_review column exists (migration)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS word_progress (
                student_id  INTEGER NOT NULL DEFAULT 1,
                word        TEXT NOT NULL,
                level       TEXT NOT NULL DEFAULT 'pre-primer',
                correct     INTEGER NOT NULL DEFAULT 0,
                attempts    INTEGER NOT NULL DEFAULT 0,
                last_seen   TEXT,
                status      TEXT NOT NULL DEFAULT 'unseen',
                next_review TEXT,
                PRIMARY KEY (student_id, word),
                FOREIGN KEY (student_id) REFERENCES students(id)
            )
        """)
        if "next_review" not in existing_cols:
            conn.execute("ALTER TABLE word_progress ADD COLUMN next_review TEXT")

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Student helpers
# ---------------------------------------------------------------------------

def create_student(name: str, pin: str = None) -> dict:
    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO students (name, pin) VALUES (?, ?)", (name.strip(), pin or None))
    conn.commit()
    row = conn.execute("SELECT * FROM students WHERE name = ?", (name.strip(),)).fetchone()
    conn.close()
    return _mask_student(dict(row))


def verify_student_pin(student_id: int, pin: str) -> bool:
    """Return True if the student has no PIN or the PIN matches."""
    conn = get_db()
    row = conn.execute("SELECT pin FROM students WHERE id = ?", (student_id,)).fetchone()
    conn.close()
    if row is None:
        return False
    stored_pin = row["pin"]
    if not stored_pin:
        return True  # no PIN set — always allowed
    return stored_pin == pin


def update_student_pin(student_id: int, pin: str = None):
    """Set or remove a student's PIN. Pass None to remove."""
    conn = get_db()
    conn.execute("UPDATE students SET pin = ? WHERE id = ?", (pin or None, student_id))
    conn.commit()
    conn.close()


def _mask_student(row: dict) -> dict:
    """Replace raw PIN with a has_pin boolean to avoid exposing PINs via API."""
    d = dict(row)
    d["has_pin"] = bool(d.pop("pin", None))
    return d


def get_students() -> list:
    conn = get_db()
    rows = conn.execute("SELECT * FROM students ORDER BY name").fetchall()
    conn.close()
    return [_mask_student(dict(r)) for r in rows]


def get_student(student_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    conn.close()
    return _mask_student(dict(row)) if row else None


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


def _spaced_repetition_interval(correct_streak: int) -> int:
    """Return review interval in days based on number of correct answers (simplified SM-2)."""
    intervals = [1, 3, 7, 14, 30]
    if correct_streak <= 0:
        return intervals[0]
    idx = min(correct_streak - 1, len(intervals) - 1)
    return intervals[idx]


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
        interval = _spaced_repetition_interval(new_correct)
        # Build the interval modifier string safely from a controlled integer value
        interval_mod = f"+{interval} days"
        conn.execute(
            """UPDATE word_progress
               SET correct = ?, attempts = ?, last_seen = datetime('now'), status = ?,
                   next_review = datetime('now', ?)
               WHERE student_id = ? AND word = ?""",
            (new_correct, new_attempts, status, interval_mod, student_id, word),
        )
    else:
        status = "learning"
        interval = _spaced_repetition_interval(1 if correct else 0)
        interval_mod = f"+{interval} days"
        conn.execute(
            """INSERT INTO word_progress (student_id, word, correct, attempts, last_seen, status, next_review)
               VALUES (?, ?, ?, 1, datetime('now'), ?, datetime('now', ?))""",
            (student_id, word, 1 if correct else 0, status, interval_mod),
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
