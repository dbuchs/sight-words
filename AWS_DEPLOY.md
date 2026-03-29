# AWS Deploy

Recommended path: AWS App Runner + DynamoDB.

Why this path:

- The app is already a standard Flask web app served by Gunicorn.
- The existing `Dockerfile` is ready for a container-based AWS service.
- This avoids Lambda adapter work and is the fastest way to production.

## 1. Rotate the OpenAI key first

The key currently shown in `.env` should be treated as exposed.

1. Go to OpenAI and rotate the API key.
2. Do not commit the replacement key to Git.
3. Store the new key in AWS App Runner as a secret or environment variable.

## 2. Create DynamoDB tables

Create these three tables in `us-east-1` unless you want a different region:

### `sight_words_students`

- Partition key: `id` Number
- Billing mode: On-demand
- Add GSI:
  - Index name: `name-index`
  - Partition key: `name` String

### `sight_words_progress`

- Partition key: `student_id` Number
- Sort key: `word` String
- Billing mode: On-demand

### `sight_words_meta`

- Partition key: `key` String
- Billing mode: On-demand

## 3. Optional one-time import from SQLite

If you want to import the existing `progress.db` on first AWS startup:

- Make sure `progress.db` is included in the image build context.
- Set `SQLITE_MIGRATION_PATH=/app/progress.db`

If you do not care about the old data:

- Do not set `SQLITE_MIGRATION_PATH`

## 4. Create an IAM role for App Runner

Grant the service permission to use DynamoDB.

Minimum table permissions:

- `dynamodb:DescribeTable`
- `dynamodb:CreateTable`
- `dynamodb:GetItem`
- `dynamodb:PutItem`
- `dynamodb:UpdateItem`
- `dynamodb:Query`
- `dynamodb:Scan`

Scope those permissions to:

- `arn:aws:dynamodb:us-east-1:<account-id>:table/sight_words_students`
- `arn:aws:dynamodb:us-east-1:<account-id>:table/sight_words_students/index/*`
- `arn:aws:dynamodb:us-east-1:<account-id>:table/sight_words_progress`
- `arn:aws:dynamodb:us-east-1:<account-id>:table/sight_words_meta`

## 5. Deploy to App Runner

Create an App Runner service from this repository or from a built container image.

Runtime settings:

- Port: `8000`
- Start command: use the image default from `Dockerfile`

Environment variables:

- `AWS_REGION=us-east-1`
- `DYNAMODB_STUDENTS_TABLE=sight_words_students`
- `DYNAMODB_PROGRESS_TABLE=sight_words_progress`
- `DYNAMODB_META_TABLE=sight_words_meta`
- `OPENAI_API_KEY=<rotated key>`
- Optional: `SQLITE_MIGRATION_PATH=/app/progress.db`

## 6. Health check

Use:

- Path: `/`

## 7. Important note about Lambda

This repo contains old Lambda URL files, but the current app is not packaged as a Lambda handler.

If you want Lambda instead of App Runner, the code should be adapted to run behind:

- Lambda Web Adapter, or
- Mangum with API Gateway or Lambda Function URL

For this codebase today, App Runner is the simpler and safer AWS path.

## VPS instead of App Runner

If you are deploying on your own VPS and only want AWS for DynamoDB:

- Use the scripts in `aws/`
- First run `aws configure`
- Then run:

```powershell
.\aws\create-dynamodb-tables.ps1
.\aws\create-iam-policy-and-user.ps1
```

The tables are created with `PAY_PER_REQUEST`, which is the cheapest per-use option.
