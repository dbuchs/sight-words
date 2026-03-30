import os
import random
import json
import re
import logging
from datetime import datetime, timezone

from flask import Flask, render_template, request, jsonify, Response
from openai import OpenAI
from dotenv import load_dotenv

import database as db
from sight_words import ORDERED_SIGHT_WORDS, WORD_LEVEL


def _load_env():
    shared_env = os.path.expanduser("~/secrets/common.env")
    if os.path.exists(shared_env):
        load_dotenv(shared_env)
    load_dotenv()


_load_env()
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = Flask(__name__)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

LEVEL_SEQUENCE = ["pre-primer", "primer", "grade1", "grade2", "grade3"]
PROMOTION_MODES = {
    "standard": {
        "label": "Standard",
        "description": "Original pacing. Follows the curriculum order closely.",
        "min_accuracy": 1.01,
        "min_words": 999,
        "min_level_mastery": 1.01,
        "level_window": 0,
    },
    "aggressive": {
        "label": "Accelerated",
        "description": "Starts introducing the next level once the current level is going well.",
        "min_accuracy": 0.85,
        "min_words": 5,
        "min_level_mastery": 0.5,
        "level_window": 1,
    },
    "fast_track": {
        "label": "Fast Track",
        "description": "Pushes strong readers into newer, harder words sooner.",
        "min_accuracy": 0.9,
        "min_words": 5,
        "min_level_mastery": 0.35,
        "level_window": 2,
    },
}

# Initialise DB on startup regardless of how Flask is invoked
db.init_db()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_student_id(data: dict) -> int:
    """Return student_id from request data, defaulting to 1."""
    sid = data.get("student_id")
    try:
        return int(sid) if sid is not None else 1
    except (ValueError, TypeError):
        return 1


def _next_sight_word(student_id: int = 1, exclude_word: str = "", seen_words: list = None):
    """Return the next sight word to teach based on current progress, spaced repetition,
    and adaptive difficulty.  seen_words lists all words already shown this session so that
    the same word is not repeated too soon."""
    # Build exclusion sets at two strictness levels so we can fall back gracefully
    # when most words have already been shown this session.
    session_seen = set(w.lower() for w in (seen_words or []))
    if exclude_word:
        session_seen.add(exclude_word.lower())
    just_exclude = {exclude_word.lower()} if exclude_word else set()

    all_progress = {r["word"]: r for r in db.get_progress(student_id=student_id)}
    student = db.get_student(student_id) or {}
    promotion_mode = student.get("promotion_mode", "standard")
    promotion_cfg = PROMOTION_MODES.get(promotion_mode, PROMOTION_MODES["standard"])

    # Compute overall accuracy for adaptive difficulty
    # (require a minimum of attempts/words to have reliable data)
    _MIN_ATTEMPTS = 3   # minimum attempts per word to count it
    _MIN_WORDS = 5      # minimum number of such words before adapting
    _STRUGGLING_THRESHOLD = 0.5  # accuracy below this → struggling

    attempted = [r for r in all_progress.values() if r.get("attempts", 0) >= _MIN_ATTEMPTS]
    accuracy = None
    if len(attempted) >= _MIN_WORDS:
        total_c = sum(r["correct"] for r in attempted)
        total_a = sum(r["attempts"] for r in attempted)
        accuracy = total_c / total_a if total_a > 0 else 0

    # Try with full session exclusion first, then fall back to only exclude_word,
    # then no exclusion at all, to prevent infinite loops on small word lists.
    for excl in (session_seen, just_exclude, set()):
        def skip(word, _excl=excl):
            return word.lower() in _excl

        # 1. Spaced-repetition reviews: learned words due now
        for word in ORDERED_SIGHT_WORDS:
            if skip(word):
                continue
            prog = all_progress.get(word.lower())
            if prog and prog["status"] == "learned" and prog.get("next_review"):
                if prog["next_review"] <= _now_str():
                    return word

        # 2. Adaptive: if student is struggling, prioritise needs_work across all levels
        if accuracy is not None and accuracy < _STRUGGLING_THRESHOLD:
            for word in ORDERED_SIGHT_WORDS:
                if skip(word):
                    continue
                prog = all_progress.get(word.lower())
                if prog and prog["status"] == "needs_work":
                    return word

        # 3. Promotion boost: for strong readers, pull in words from the next level sooner.
        accelerated_word = _pick_accelerated_word(
            all_progress,
            skip,
            accuracy,
            attempted_count=len(attempted),
            promotion_cfg=promotion_cfg,
        )
        if accelerated_word:
            return accelerated_word

        # 4. Next unseen / learning / needs_work word in curriculum order
        for word in ORDERED_SIGHT_WORDS:
            if skip(word):
                continue
            prog = all_progress.get(word.lower())
            if prog is None or prog["status"] in ("unseen", "learning", "needs_work"):
                return word

        # 5. All learned — fall back to any needs_work word
        for word in ORDERED_SIGHT_WORDS:
            if skip(word):
                continue
            prog = all_progress.get(word.lower())
            if prog and prog["status"] == "needs_work":
                return word

    return ORDERED_SIGHT_WORDS[0]


def _now_str() -> str:
    """Return current UTC datetime as SQLite-compatible string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse_schedule_datetime(value: str) -> str:
    """Convert date/datetime-local input into the app's stored timestamp format."""
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValueError("next_review is required")

    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            if fmt == "%Y-%m-%d":
                parsed = parsed.replace(hour=0, minute=0, second=0)
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    raise ValueError("Invalid next_review format")


def _is_unfinished(prog: dict | None) -> bool:
    return prog is None or prog["status"] in ("unseen", "learning", "needs_work")


def _level_mastery(level: str, all_progress: dict) -> float:
    words = [w for w in ORDERED_SIGHT_WORDS if WORD_LEVEL.get(w.lower()) == level]
    if not words:
        return 0.0
    learned = sum(
        1 for word in words
        if (all_progress.get(word.lower()) or {}).get("status") == "learned"
    )
    return learned / len(words)


def _pick_first_unfinished(levels: list[str], all_progress: dict, skip) -> str | None:
    level_set = set(levels)
    for word in ORDERED_SIGHT_WORDS:
        if skip(word):
            continue
        if WORD_LEVEL.get(word.lower(), "pre-primer") not in level_set:
            continue
        if _is_unfinished(all_progress.get(word.lower())):
            return word
    return None


def _pick_accelerated_word(
    all_progress: dict,
    skip,
    accuracy: float | None,
    attempted_count: int,
    promotion_cfg: dict,
) -> str | None:
    if promotion_cfg["level_window"] <= 0:
        return None
    if accuracy is None or accuracy < promotion_cfg["min_accuracy"]:
        return None
    if attempted_count < promotion_cfg["min_words"]:
        return None

    current_level = None
    for level in LEVEL_SEQUENCE:
        has_unfinished = any(
            _is_unfinished(all_progress.get(word.lower()))
            for word in ORDERED_SIGHT_WORDS
            if WORD_LEVEL.get(word.lower(), "pre-primer") == level
        )
        if has_unfinished:
            current_level = level
            break

    if current_level is None:
        return None

    if _level_mastery(current_level, all_progress) < promotion_cfg["min_level_mastery"]:
        return None

    current_idx = LEVEL_SEQUENCE.index(current_level)
    target_levels = LEVEL_SEQUENCE[
        current_idx + 1: current_idx + 1 + promotion_cfg["level_window"]
    ]
    if not target_levels:
        return None

    return _pick_first_unfinished(target_levels, all_progress, skip)


def _generate_sentence(sight_word: str, additional_context: str = "") -> str:
    """Ask GPT to generate a child-friendly sentence using the given sight word."""
    prompt = (
        f"Write exactly one short, simple sentence (6-10 words) for a 5-7 year old child. "
        f"The sentence MUST include the word \"{sight_word}\". "
        f"Use easy phonetic words a young child can sound out. "
        f"Make it fun and child-friendly. "
        f"{additional_context}"
        f"Return ONLY the sentence, no quotes, no punctuation besides end punctuation."
    )
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=60,
        temperature=0.8,
    )
    sentence = response.choices[0].message.content.strip().strip('"').strip("'")
    if sentence and sentence[-1] not in ".!?":
        sentence += "."
    return sentence


def _pick_test_words(sentence: str, sight_word: str, count: int = 2, student_id: int = 1) -> list:
    """Pick additional words from the sentence to test (non-sight-word).

    Priority: needs_work / learning words first, then unseen words, then
    learned words as a last resort (so already-mastered words like 'the'
    are not repeated once the student has succeeded with them).
    """
    words = [re.sub(r"[^a-zA-Z'-]", "", w) for w in sentence.split()]
    words = [w for w in words if w and w.lower() != sight_word.lower()]
    all_prog = {r["word"]: r for r in db.get_progress(student_id=student_id)}

    def _status(w):
        return all_prog.get(w.lower(), {}).get("status", "unseen")

    needs_practice = [w for w in words if _status(w) in ("needs_work", "learning")]
    unseen = [w for w in words if _status(w) == "unseen"]
    learned = [w for w in words if _status(w) == "learned"]

    random.shuffle(needs_practice)
    random.shuffle(unseen)
    random.shuffle(learned)
    pool = needs_practice + unseen + learned  # learned words are last resort

    # Deduplicate while preserving order
    seen_set = set()
    unique = []
    for w in pool:
        if w.lower() not in seen_set:
            seen_set.add(w.lower())
            unique.append(w)
    return unique[:count]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    students = db.get_students()
    return render_template("index.html", students=students, sight_words=ORDERED_SIGHT_WORDS)


@app.route("/teacher")
def teacher():
    student_id = int(request.args.get("student_id", 1))
    all_progress = db.get_progress(student_id=student_id)
    # Build full word list with progress data merged in
    progress_map = {r["word"]: r for r in all_progress}
    words_data = []
    for word in ORDERED_SIGHT_WORDS:
        prog = progress_map.get(word.lower(), {
            "word": word.lower(),
            "level": WORD_LEVEL.get(word.lower(), "pre-primer"),
            "correct": 0,
            "attempts": 0,
            "interval": 1,
            "status": "unseen",
            "last_seen": None,
            "next_review": None,
        })
        accuracy = round(prog["correct"] / prog["attempts"] * 100) if prog["attempts"] > 0 else 0
        prog["accuracy"] = accuracy
        prog["display_word"] = word
        words_data.append(prog)

    # Group by level
    levels = LEVEL_SEQUENCE
    grouped = {lvl: [] for lvl in levels}
    for w in words_data:
        lvl = WORD_LEVEL.get(w["display_word"].lower(), "pre-primer")
        grouped[lvl].append(w)

    students = db.get_students()
    current_student = db.get_student(student_id)
    return render_template(
        "teacher.html",
        grouped=grouped,
        levels=levels,
        words_data=words_data,
        students=students,
        current_student=current_student,
        student_id=student_id,
        promotion_modes=PROMOTION_MODES,
    )


@app.route("/api/students", methods=["GET"])
def list_students():
    return jsonify(db.get_students())


@app.route("/api/students", methods=["POST"])
def create_student():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    pin = (data.get("pin") or "").strip() or None
    if not name:
        return jsonify({"error": "name is required"}), 400
    student = db.create_student(name, pin=pin)
    return jsonify(student), 201


@app.route("/api/students/<int:student_id>/verify-pin", methods=["POST"])
def verify_pin(student_id):
    data = request.get_json() or {}
    pin = data.get("pin", "")
    if db.verify_student_pin(student_id, pin):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Incorrect PIN"}), 403


@app.route("/api/students/<int:student_id>/pin", methods=["PUT"])
def update_pin(student_id):
    """Update or remove a student's PIN. Send {"pin": "1234"} to set, {"pin": null} to remove."""
    data = request.get_json() or {}
    pin = (data.get("pin") or "").strip() or None
    db.update_student_pin(student_id, pin)
    return jsonify({"ok": True})


@app.route("/api/students/<int:student_id>/promotion-mode", methods=["PUT"])
def update_promotion_mode(student_id):
    """Update a student's promotion aggressiveness."""
    data = request.get_json() or {}
    promotion_mode = (data.get("promotion_mode") or "").strip()
    if promotion_mode not in PROMOTION_MODES:
        return jsonify({"error": "Invalid promotion mode"}), 400
    db.update_student_promotion_mode(student_id, promotion_mode)
    return jsonify({"ok": True, "promotion_mode": promotion_mode})


@app.route("/api/generate-lesson", methods=["POST"])
def generate_lesson():
    """Generate a two-sentence lesson for the next (or requested) sight word."""
    data = request.get_json() or {}
    student_id = _resolve_student_id(data)
    previous_word = data.get("previous_word", "")
    seen_words = data.get("seen_words") or []
    sight_word = data.get("word") or _next_sight_word(
        student_id=student_id, exclude_word=previous_word, seen_words=seen_words
    )
    sight_word_lower = sight_word.lower()

    # Ensure the word is in the DB
    level = WORD_LEVEL.get(sight_word_lower, "pre-primer")
    db.set_word_level(sight_word, level, student_id=student_id)

    # Generate demo sentence (read aloud by app)
    demo_sentence = _generate_sentence(
        sight_word,
        "The sentence will be read aloud to the child as a demonstration."
    )

    # Generate practice sentence (student reads independently)
    practice_sentence = _generate_sentence(
        sight_word,
        "This sentence is for the child to read aloud on their own, then identify words. "
        "Make it different from the first sentence."
    )

    # Pick 2 extra words to test from the practice sentence
    test_words = _pick_test_words(
        practice_sentence, sight_word, count=2, student_id=student_id
    )

    return jsonify({
        "sight_word": sight_word,
        "demo_sentence": demo_sentence,
        "practice_sentence": practice_sentence,
        "test_words": test_words,
    })


@app.route("/api/record-progress", methods=["POST"])
def record_progress():
    """Record a correct or incorrect word-click attempt."""
    data = request.get_json() or {}
    word = data.get("word", "").strip()
    correct = bool(data.get("correct", False))
    student_id = _resolve_student_id(data)

    if not word:
        return jsonify({"error": "word is required"}), 400

    updated = db.record_attempt(word, correct, student_id=student_id)
    return jsonify(updated)


@app.route("/api/progress")
def get_all_progress():
    student_id = int(request.args.get("student_id", 1))
    return jsonify(db.get_progress(student_id=student_id))


@app.route("/api/progress/<word>")
def get_word_progress(word):
    student_id = int(request.args.get("student_id", 1))
    prog = db.get_progress(word, student_id=student_id)
    if prog is None:
        return jsonify({"word": word, "status": "unseen", "correct": 0, "attempts": 0}), 200
    return jsonify(prog)


@app.route("/api/progress/<word>/schedule", methods=["PUT"])
def update_word_schedule(word):
    data = request.get_json() or {}
    student_id = _resolve_student_id(data)

    try:
        interval = int(data.get("interval"))
    except (TypeError, ValueError):
        return jsonify({"error": "interval must be a whole number"}), 400

    if interval < 0:
        return jsonify({"error": "interval must be zero or greater"}), 400

    try:
        next_review = _parse_schedule_datetime(data.get("next_review", ""))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    level = WORD_LEVEL.get(word.lower(), "pre-primer")
    updated = db.update_word_schedule(
        word,
        interval=interval,
        next_review=next_review,
        student_id=student_id,
        level=level,
    )
    return jsonify(updated)


@app.route("/api/tts", methods=["POST"])
def tts():
    """Proxy TTS request to OpenAI and return audio bytes.
    Optional mode='word' uses pronunciation-focused instructions for isolated words."""
    data = request.get_json() or {}
    text = data.get("text", "").strip()
    mode = data.get("mode", "sentence")
    if not text:
        return jsonify({"error": "text is required"}), 400

    if mode == "word":
        instructions = (
            "Say this single word slowly and very clearly, as if teaching a child to read it. "
            "Give the word its full, natural pronunciation — not embedded in a sentence."
        )
    else:
        instructions = "Speak very slowly and distinctly, enunciating each word, for dictation."

    response = client.audio.speech.create(
        model="tts-1-hd",
        voice="nova",
        input=text,
        response_format="mp3",
        instructions=instructions,
    )
    audio_bytes = response.content
    return Response(audio_bytes, mimetype="audio/mpeg")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1", port=5000)
