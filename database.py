import os
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError


AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
DYNAMODB_ENDPOINT_URL = os.environ.get("DYNAMODB_ENDPOINT_URL")
STUDENTS_TABLE = os.environ.get("DYNAMODB_STUDENTS_TABLE", "sight_words_students")
PROGRESS_TABLE = os.environ.get("DYNAMODB_PROGRESS_TABLE", "sight_words_progress")
META_TABLE = os.environ.get("DYNAMODB_META_TABLE", "sight_words_meta")
SQLITE_MIGRATION_PATH = os.environ.get("SQLITE_MIGRATION_PATH") or os.environ.get("DB_PATH")


def _dynamodb_resource():
    kwargs = {"region_name": AWS_REGION}
    if DYNAMODB_ENDPOINT_URL:
        kwargs["endpoint_url"] = DYNAMODB_ENDPOINT_URL
    return boto3.resource("dynamodb", **kwargs)


def _dynamodb_client():
    kwargs = {"region_name": AWS_REGION}
    if DYNAMODB_ENDPOINT_URL:
        kwargs["endpoint_url"] = DYNAMODB_ENDPOINT_URL
    return boto3.client("dynamodb", **kwargs)


def _students_table():
    return _dynamodb_resource().Table(STUDENTS_TABLE)


def _progress_table():
    return _dynamodb_resource().Table(PROGRESS_TABLE)


def _meta_table():
    return _dynamodb_resource().Table(META_TABLE)


def _normalize_value(value):
    if isinstance(value, list):
        return [_normalize_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize_value(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    return value


def _normalize_item(item):
    return _normalize_value(item or {})


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _future_str(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _spaced_repetition_interval(correct_streak: int) -> int:
    intervals = [1, 3, 7, 14, 30]
    if correct_streak <= 0:
        return intervals[0]
    idx = min(correct_streak - 1, len(intervals) - 1)
    return intervals[idx]


def _mask_student(row: dict) -> dict:
    d = dict(row)
    d["has_pin"] = bool(d.pop("pin", None))
    return d


def _ensure_students_table():
    client = _dynamodb_client()
    try:
        client.describe_table(TableName=STUDENTS_TABLE)
        return
    except client.exceptions.ResourceNotFoundException:
        pass

    client.create_table(
        TableName=STUDENTS_TABLE,
        AttributeDefinitions=[
            {"AttributeName": "id", "AttributeType": "N"},
            {"AttributeName": "name", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
        GlobalSecondaryIndexes=[
            {
                "IndexName": "name-index",
                "KeySchema": [{"AttributeName": "name", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )
    client.get_waiter("table_exists").wait(TableName=STUDENTS_TABLE)


def _ensure_progress_table():
    client = _dynamodb_client()
    try:
        client.describe_table(TableName=PROGRESS_TABLE)
        return
    except client.exceptions.ResourceNotFoundException:
        pass

    client.create_table(
        TableName=PROGRESS_TABLE,
        AttributeDefinitions=[
            {"AttributeName": "student_id", "AttributeType": "N"},
            {"AttributeName": "word", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "student_id", "KeyType": "HASH"},
            {"AttributeName": "word", "KeyType": "RANGE"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    client.get_waiter("table_exists").wait(TableName=PROGRESS_TABLE)


def _ensure_meta_table():
    client = _dynamodb_client()
    try:
        client.describe_table(TableName=META_TABLE)
        return
    except client.exceptions.ResourceNotFoundException:
        pass

    client.create_table(
        TableName=META_TABLE,
        AttributeDefinitions=[{"AttributeName": "key", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "key", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
    )
    client.get_waiter("table_exists").wait(TableName=META_TABLE)


def _ensure_default_records():
    _students_table().put_item(
        Item={
            "id": 1,
            "name": "Default",
            "pin": None,
            "promotion_mode": "standard",
        },
        ConditionExpression="attribute_not_exists(id)",
    )


def _ensure_meta_counter():
    try:
        _meta_table().put_item(
            Item={"key": "student_id_counter", "value": 1},
            ConditionExpression="attribute_not_exists(#key)",
            ExpressionAttributeNames={"#key": "key"},
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise


def _progress_has_data() -> bool:
    response = _progress_table().scan(Select="COUNT", Limit=1)
    return response.get("Count", 0) > 0


def _migration_done() -> bool:
    response = _meta_table().get_item(Key={"key": "migration:sqlite_imported"})
    return "Item" in response


def _update_counter_from_existing_students():
    students = get_students()
    max_id = max((student["id"] for student in students), default=1)
    _meta_table().put_item(Item={"key": "student_id_counter", "value": max_id})


def _maybe_migrate_sqlite():
    if not SQLITE_MIGRATION_PATH:
        return
    if not os.path.exists(SQLITE_MIGRATION_PATH):
        return
    if _migration_done():
        return
    if _progress_has_data():
        return

    conn = sqlite3.connect(SQLITE_MIGRATION_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with _students_table().batch_writer() as batch:
            for row in conn.execute(
                "SELECT id, name, pin, COALESCE(promotion_mode, 'standard') AS promotion_mode FROM students"
            ).fetchall():
                batch.put_item(Item=_normalize_item(dict(row)))

        with _progress_table().batch_writer() as batch:
            for row in conn.execute(
                """
                SELECT
                    COALESCE(student_id, 1) AS student_id,
                    word,
                    COALESCE(level, 'pre-primer') AS level,
                    COALESCE(correct, 0) AS correct,
                    COALESCE(attempts, 0) AS attempts,
                    last_seen,
                    COALESCE(status, 'unseen') AS status,
                    next_review
                FROM word_progress
                """
            ).fetchall():
                item = _normalize_item(dict(row))
                item["word"] = (item.get("word") or "").lower()
                if item["word"]:
                    batch.put_item(Item=item)
    finally:
        conn.close()

    _update_counter_from_existing_students()
    _meta_table().put_item(
        Item={
            "key": "migration:sqlite_imported",
            "source": SQLITE_MIGRATION_PATH,
            "imported_at": _now_str(),
        }
    )


def init_db():
    _ensure_students_table()
    _ensure_progress_table()
    _ensure_meta_table()
    _ensure_meta_counter()
    try:
        _ensure_default_records()
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
    _maybe_migrate_sqlite()


def _get_student_by_name(name: str):
    response = _students_table().query(
        IndexName="name-index",
        KeyConditionExpression=Key("name").eq(name),
        Limit=1,
    )
    items = response.get("Items", [])
    return _normalize_item(items[0]) if items else None


def _next_student_id() -> int:
    response = _meta_table().update_item(
        Key={"key": "student_id_counter"},
        UpdateExpression="ADD #value :one",
        ExpressionAttributeNames={"#value": "value"},
        ExpressionAttributeValues={":one": 1},
        ReturnValues="UPDATED_NEW",
    )
    return int(_normalize_item(response["Attributes"])["value"])


def create_student(name: str, pin: str = None, promotion_mode: str = "standard") -> dict:
    cleaned_name = name.strip()
    existing = _get_student_by_name(cleaned_name)
    if existing:
        return _mask_student(existing)

    student = {
        "id": _next_student_id(),
        "name": cleaned_name,
        "pin": pin or None,
        "promotion_mode": promotion_mode or "standard",
    }
    _students_table().put_item(Item=student)
    return _mask_student(student)


def verify_student_pin(student_id: int, pin: str) -> bool:
    row = get_student(student_id, include_pin=True)
    if row is None:
        return False
    stored_pin = row.get("pin")
    if not stored_pin:
        return True
    return stored_pin == pin


def update_student_pin(student_id: int, pin: str = None):
    _students_table().update_item(
        Key={"id": student_id},
        UpdateExpression="SET pin = :pin",
        ExpressionAttributeValues={":pin": pin or None},
    )


def update_student_promotion_mode(student_id: int, promotion_mode: str = "standard"):
    _students_table().update_item(
        Key={"id": student_id},
        UpdateExpression="SET promotion_mode = :promotion_mode",
        ExpressionAttributeValues={":promotion_mode": promotion_mode or "standard"},
    )


def get_students() -> list:
    table = _students_table()
    items = []
    response = table.scan()
    items.extend(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))
    students = [_mask_student(_normalize_item(item)) for item in items]
    return sorted(students, key=lambda student: student["name"].lower())


def get_student(student_id: int, include_pin: bool = False):
    response = _students_table().get_item(Key={"id": student_id})
    item = response.get("Item")
    if not item:
        return None
    student = _normalize_item(item)
    return student if include_pin else _mask_student(student)


def get_progress(word=None, student_id: int = 1):
    if word:
        response = _progress_table().get_item(
            Key={"student_id": student_id, "word": word.lower()}
        )
        item = response.get("Item")
        return _normalize_item(item) if item else None

    table = _progress_table()
    items = []
    response = table.query(
        KeyConditionExpression=Key("student_id").eq(student_id),
        ScanIndexForward=True,
    )
    items.extend(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        response = table.query(
            KeyConditionExpression=Key("student_id").eq(student_id),
            ScanIndexForward=True,
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))
    return [_normalize_item(item) for item in items]


def record_attempt(word, correct: bool, student_id: int = 1):
    cleaned_word = word.lower()
    row = get_progress(cleaned_word, student_id=student_id)

    if row:
        new_correct = row["correct"] + (1 if correct else 0)
        new_attempts = row["attempts"] + 1
        level = row.get("level", "pre-primer")
    else:
        new_correct = 1 if correct else 0
        new_attempts = 1
        level = "pre-primer"

    accuracy = new_correct / new_attempts
    if accuracy >= 0.8 and new_attempts >= 3:
        status = "learned"
    elif accuracy < 0.5 and new_attempts >= 3:
        status = "needs_work"
    else:
        status = "learning"

    interval = _spaced_repetition_interval(new_correct)
    _progress_table().put_item(
        Item={
            "student_id": student_id,
            "word": cleaned_word,
            "level": level,
            "correct": new_correct,
            "attempts": new_attempts,
            "last_seen": _now_str(),
            "status": status,
            "next_review": _future_str(interval),
        }
    )

    return get_progress(cleaned_word, student_id=student_id)


def set_word_level(word, level, student_id: int = 1):
    existing = get_progress(word, student_id=student_id)
    item = {
        "student_id": student_id,
        "word": word.lower(),
        "level": level,
        "correct": existing["correct"] if existing else 0,
        "attempts": existing["attempts"] if existing else 0,
        "last_seen": existing.get("last_seen") if existing else None,
        "status": existing["status"] if existing else "unseen",
        "next_review": existing.get("next_review") if existing else None,
    }
    _progress_table().put_item(Item=item)
