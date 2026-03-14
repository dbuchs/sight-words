#!/usr/bin/env python3
"""Migrate sight-words data from SQLite into DynamoDB."""

import argparse
import sqlite3

import boto3


def fetch_rows(conn, query):
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(query).fetchall()]


def put_students(ddb, table_name, rows):
    table = ddb.Table(table_name)
    # metadata item for id allocation compatibility
    max_id = max([r["id"] for r in rows], default=1)
    table.put_item(Item={"student_id": 0, "next_student_id": max_id + 1})

    for r in rows:
        table.put_item(
            Item={
                "student_id": int(r["id"]),
                "name": r["name"],
                "pin": r.get("pin"),
            }
        )


def put_progress(ddb, table_name, rows):
    table = ddb.Table(table_name)
    for r in rows:
        table.put_item(
            Item={
                "student_id": int(r["student_id"]),
                "word": r["word"],
                "level": r.get("level") or "pre-primer",
                "correct": int(r.get("correct") or 0),
                "attempts": int(r.get("attempts") or 0),
                "last_seen": r.get("last_seen"),
                "status": r.get("status") or "unseen",
                "next_review": r.get("next_review"),
            }
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite-path", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--ddb-endpoint-url", default=None)
    parser.add_argument("--students-table", default="sight_words_students")
    parser.add_argument("--progress-table", default="sight_words_progress")
    args = parser.parse_args()

    conn = sqlite3.connect(args.sqlite_path)

    students = fetch_rows(conn, "SELECT id, name, pin FROM students ORDER BY id")
    progress = fetch_rows(
        conn,
        """
        SELECT student_id, word, level, correct, attempts, last_seen, status, next_review
        FROM word_progress
        ORDER BY student_id, word
        """,
    )
    conn.close()

    ddb = boto3.resource("dynamodb", region_name=args.region, endpoint_url=args.ddb_endpoint_url)
    put_students(ddb, args.students_table, students)
    put_progress(ddb, args.progress_table, progress)

    print(f"Migrated {len(students)} students and {len(progress)} progress rows.")


if __name__ == "__main__":
    main()
