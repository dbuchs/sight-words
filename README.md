# sight-words

This app now stores students and word progress in DynamoDB instead of SQLite.

## Shared secrets file

Store runtime secrets in `~/secrets/common.env`.

The app now loads that file automatically for:

- local Python runs
- `docker compose`

Keep `.env` for temporary local-only overrides if you want, but the intended source of truth is `~/secrets/common.env`.

Example:

```env
OPENAI_API_KEY=replace_me
AWS_REGION=us-east-1
DYNAMODB_STUDENTS_TABLE=sight_words_students
DYNAMODB_PROGRESS_TABLE=sight_words_progress
DYNAMODB_META_TABLE=sight_words_meta
```

If you are using an IAM user with access keys locally, add these too:

```env
AWS_ACCESS_KEY_ID=replace_me
AWS_SECRET_ACCESS_KEY=replace_me
```

If you are using DynamoDB Local, also set:

```env
DYNAMODB_ENDPOINT_URL=http://localhost:8000
```

## Required environment variables

- `AWS_REGION`: AWS region for DynamoDB, for example `us-east-1`
- `DYNAMODB_STUDENTS_TABLE`: Optional, defaults to `sight_words_students`
- `DYNAMODB_PROGRESS_TABLE`: Optional, defaults to `sight_words_progress`
- `DYNAMODB_META_TABLE`: Optional, defaults to `sight_words_meta`
- `DYNAMODB_ENDPOINT_URL`: Optional, set this when using DynamoDB Local

## Optional SQLite import

If you want to carry forward data from the old `progress.db`, set one of these before the first startup:

- `SQLITE_MIGRATION_PATH=progress.db`
- or keep `DB_PATH=progress.db`

On first run, the app will create the DynamoDB tables if needed and import the SQLite data once.

## Fresh start setup

1. Create `~/secrets/common.env`.
2. Put your AWS and app variables in that file.
3. Make sure the AWS identity you use can access DynamoDB.
4. Start the app.

For local Docker:

```powershell
docker compose up --build
```

For local Flask:

```powershell
.\\venv\\Scripts\\python.exe app.py
```

The app will:

- connect to DynamoDB in `AWS_REGION`
- create the three tables if they do not exist
- optionally import `progress.db` if `SQLITE_MIGRATION_PATH` is set
