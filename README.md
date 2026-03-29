# sight-words

This app now stores students and word progress in DynamoDB instead of SQLite.

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
