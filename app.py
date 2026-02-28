import os
import random
import json
import re
from datetime import datetime, timezone

from flask import Flask, render_template, request, jsonify, Response
from openai import OpenAI
from dotenv import load_dotenv

import database as db
from sight_words import ORDERED_SIGHT_WORDS, WORD_LEVEL

load_dotenv()

app = Flask(__name__)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

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

        # 3. Next unseen / learning / needs_work word in curriculum order
        for word in ORDERED_SIGHT_WORDS:
            if skip(word):
                continue
            prog = all_progress.get(word.lower())
            if prog is None or prog["status"] in ("unseen", "learning", "needs_work"):
                return word

        # 4. All learned — fall back to any needs_work word
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


def _learned_words(exclude=None, student_id: int = 1):
    """Return words with status 'learned' (excluding the given word)."""
    all_progress = db.get_progress(student_id=student_id)
    learned = [
        r["word"] for r in all_progress
        if r["status"] == "learned" and r["word"] != (exclude or "").lower()
    ]
    return learned


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
    """Pick additional words from the sentence to test (non-sight-word)."""
    words = [re.sub(r"[^a-zA-Z'-]", "", w) for w in sentence.split()]
    words = [w for w in words if w and w.lower() != sight_word.lower()]
    # Prefer previously learned sight words; fall back to any word
    learned = set(_learned_words(exclude=sight_word, student_id=student_id))
    preferred = [w for w in words if w.lower() in learned]
    others = [w for w in words if w.lower() not in learned]
    random.shuffle(preferred)
    random.shuffle(others)
    pool = preferred + others
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for w in pool:
        if w.lower() not in seen:
            seen.add(w.lower())
            unique.append(w)
    return unique[:count]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    students = db.get_students()
    return render_template("index.html", students=students)


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
            "status": "unseen",
            "last_seen": None,
        })
        accuracy = round(prog["correct"] / prog["attempts"] * 100) if prog["attempts"] > 0 else 0
        prog["accuracy"] = accuracy
        prog["display_word"] = word
        words_data.append(prog)

    # Group by level
    levels = ["pre-primer", "primer", "grade1", "grade2", "grade3"]
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
        students=students,
        current_student=current_student,
        student_id=student_id,
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
