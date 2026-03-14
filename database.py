import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError


AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
DDB_ENDPOINT_URL = os.environ.get("DDB_ENDPOINT_URL")
STUDENTS_TABLE = os.environ.get("DDB_STUDENTS_TABLE", "sight_words_students")
PROGRESS_TABLE = os.environ.get("DDB_PROGRESS_TABLE", "sight_words_progress")


def _dynamodb_resource():
    return boto3.resource("dynamodb", region_name=AWS_REGION, endpoint_url=DDB_ENDPOINT_URL)


def _students_table():
    return _dynamodb_resource().Table(STUDENTS_TABLE)


def _progress_table():
    return _dynamodb_resource().Table(PROGRESS_TABLE)


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _to_decimal(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_decimal(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_decimal(v) for v in value]
    return value


def _from_decimal(value):
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {k: _from_decimal(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_decimal(v) for v in value]
    return value


def init_db():
    """Bootstrap metadata and ensure the default student exists."""
    table = _students_table()

    # Create/initialize metadata counter item.
    table.update_item(
        Key={"student_id": 0},
        UpdateExpression="SET next_student_id = if_not_exists(next_student_id, :next)",
        ExpressionAttributeValues={":next": 1},
    )

    # Ensure default student exists and advance counter as needed.
    try:
        table.put_item(
            Item={"student_id": 1, "name": "Default", "pin": None},
            ConditionExpression="attribute_not_exists(student_id)",
        )
        table.update_item(
            Key={"student_id": 0},
            UpdateExpression="SET next_student_id = :next",
            ExpressionAttributeValues={":next": 2},
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise


def create_student(name: str, pin: str = None) -> dict:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("name is required")

    # Preserve previous behavior where names are globally unique.
    existing = _students_table().scan(
        FilterExpression="#n = :name",
        ExpressionAttributeNames={"#n": "name"},
        ExpressionAttributeValues={":name": clean_name},
    ).get("Items", [])
    if existing:
        return _mask_student(_from_decimal(existing[0]))

    counter = _students_table().update_item(
        Key={"student_id": 0},
        UpdateExpression="ADD next_student_id :inc",
        ExpressionAttributeValues={":inc": 1},
        ReturnValues="UPDATED_NEW",
    )
    new_id = int(counter["Attributes"]["next_student_id"]) - 1

    item = {"student_id": new_id, "name": clean_name, "pin": pin or None}
    _students_table().put_item(Item=item)
    return _mask_student(item)


def verify_student_pin(student_id: int, pin: str) -> bool:
    row = _students_table().get_item(Key={"student_id": int(student_id)}).get("Item")
    if row is None:
        return False
    stored_pin = row.get("pin")
    if not stored_pin:
        return True
    return stored_pin == pin


def update_student_pin(student_id: int, pin: str = None):
    _students_table().update_item(
        Key={"student_id": int(student_id)},
        UpdateExpression="SET pin = :pin",
        ExpressionAttributeValues={":pin": pin or None},
    )


def _mask_student(row: dict) -> dict:
    d = dict(row)
    d["has_pin"] = bool(d.pop("pin", None))
    return d


def get_students() -> list:
    items = _students_table().scan().get("Items", [])
    students = [_mask_student(_from_decimal(r)) for r in items if int(r.get("student_id", 0)) != 0]
    return sorted(students, key=lambda s: s["name"].lower())


def get_student(student_id: int):
    row = _students_table().get_item(Key={"student_id": int(student_id)}).get("Item")
    return _mask_student(_from_decimal(row)) if row else None


def get_progress(word=None, student_id: int = 1):
    table = _progress_table()
    sid = int(student_id)
    if word:
        row = table.get_item(Key={"student_id": sid, "word": word.lower()}).get("Item")
        return _from_decimal(row) if row else None

    rows = table.query(
        KeyConditionExpression=Key("student_id").eq(sid),
    ).get("Items", [])
    rows = [_from_decimal(r) for r in rows]
    return sorted(rows, key=lambda r: r["word"])


def _spaced_repetition_interval(correct_streak: int) -> int:
    intervals = [1, 3, 7, 14, 30]
    if correct_streak <= 0:
        return intervals[0]
    idx = min(correct_streak - 1, len(intervals) - 1)
    return intervals[idx]


def record_attempt(word, correct: bool, student_id: int = 1):
    table = _progress_table()
    sid = int(student_id)
    clean_word = word.lower()
    row = table.get_item(Key={"student_id": sid, "word": clean_word}).get("Item")
    now = _now_str()

    if row:
        row = _from_decimal(row)
        new_correct = row["correct"] + (1 if correct else 0)
        new_attempts = row["attempts"] + 1
    else:
        new_correct = 1 if correct else 0
        new_attempts = 1

    accuracy = (new_correct / new_attempts) if new_attempts else 0
    if accuracy >= 0.8 and new_attempts >= 3:
        status = "learned"
    elif accuracy < 0.5 and new_attempts >= 3:
        status = "needs_work"
    else:
        status = "learning"

    next_days = _spaced_repetition_interval(new_correct)
    next_review = (datetime.now(timezone.utc) + timedelta(days=next_days)).strftime("%Y-%m-%d %H:%M:%S")

    item = {
        "student_id": sid,
        "word": clean_word,
        "level": (row.get("level") if row else "pre-primer") or "pre-primer",
        "correct": new_correct,
        "attempts": new_attempts,
        "last_seen": now,
        "status": status,
        "next_review": next_review,
    }
    table.put_item(Item=_to_decimal(item))
    return get_progress(clean_word, student_id=sid)


def set_word_level(word, level, student_id: int = 1):
    table = _progress_table()
    sid = int(student_id)
    clean_word = word.lower()
    row = table.get_item(Key={"student_id": sid, "word": clean_word}).get("Item")

    if row:
        table.update_item(
            Key={"student_id": sid, "word": clean_word},
            UpdateExpression="SET #lvl = :level",
            ExpressionAttributeNames={"#lvl": "level"},
            ExpressionAttributeValues={":level": level},
        )
        return

    table.put_item(
        Item={
            "student_id": sid,
            "word": clean_word,
            "level": level,
            "correct": 0,
            "attempts": 0,
            "last_seen": None,
            "status": "unseen",
            "next_review": None,
        }
    )
