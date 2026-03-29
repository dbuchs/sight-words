# AWS DynamoDB Setup

This is the clean restart path for this app.

Use one shared secrets file:

- `~/secrets/common.env`

Use that same file for:

- local Python runs
- `docker compose`
- VPS/container deploys where you inject env vars from a file

## 0. Rotate exposed credentials first

The AWS access key, AWS secret key, and OpenAI key that were placed in `.env` should be treated as exposed.

Before using this app again:

1. Delete or disable the exposed AWS access key in AWS IAM.
2. Create a new credential only if you actually need long-lived keys.
3. Rotate the OpenAI API key.
4. Move all replacement secrets into `~/secrets/common.env`.

## 1. Decide how the app will authenticate to AWS

You have two valid options.

### Option A: IAM role

Best for:

- App Runner
- EC2
- ECS
- any AWS-hosted runtime

In this setup, do not put `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` in `common.env`.

Set only:

```env
OPENAI_API_KEY=replace_me
AWS_REGION=us-east-1
DYNAMODB_STUDENTS_TABLE=sight_words_students
DYNAMODB_PROGRESS_TABLE=sight_words_progress
DYNAMODB_META_TABLE=sight_words_meta
```

### Option B: IAM user access keys

Best for:

- local development on your own machine
- a VPS outside AWS

Use a dedicated least-privilege IAM user, not your personal admin user.

Example `~/secrets/common.env`:

```env
OPENAI_API_KEY=replace_me
AWS_ACCESS_KEY_ID=replace_me
AWS_SECRET_ACCESS_KEY=replace_me
AWS_REGION=us-east-1
DYNAMODB_STUDENTS_TABLE=sight_words_students
DYNAMODB_PROGRESS_TABLE=sight_words_progress
DYNAMODB_META_TABLE=sight_words_meta
```

## 2. Create the DynamoDB tables

The app can auto-create tables on startup if the AWS identity has `dynamodb:CreateTable`.

Or you can create them ahead of time with:

```powershell
.\aws\create-dynamodb-tables.ps1
```

Expected tables:

### `sight_words_students`

- Partition key: `id` Number
- Billing mode: `PAY_PER_REQUEST`
- GSI: `name-index` on `name` String

### `sight_words_progress`

- Partition key: `student_id` Number
- Sort key: `word` String
- Billing mode: `PAY_PER_REQUEST`

### `sight_words_meta`

- Partition key: `key` String
- Billing mode: `PAY_PER_REQUEST`

## 3. Grant the right permissions

Minimum permissions:

- `dynamodb:DescribeTable`
- `dynamodb:CreateTable`
- `dynamodb:GetItem`
- `dynamodb:PutItem`
- `dynamodb:UpdateItem`
- `dynamodb:Query`
- `dynamodb:Scan`

For a VPS or local machine using an IAM user, you can create a least-privilege user with:

```powershell
.\aws\create-iam-policy-and-user.ps1
```

That script expects your AWS CLI to already be authenticated.

## 4. Put secrets in `~/secrets/common.env`

Create the directory if needed:

```powershell
New-Item -ItemType Directory -Force "$HOME\\secrets"
```

Create the file:

```powershell
@'
OPENAI_API_KEY=replace_me
AWS_ACCESS_KEY_ID=replace_me
AWS_SECRET_ACCESS_KEY=replace_me
AWS_REGION=us-east-1
DYNAMODB_STUDENTS_TABLE=sight_words_students
DYNAMODB_PROGRESS_TABLE=sight_words_progress
DYNAMODB_META_TABLE=sight_words_meta
'@ | Set-Content -Encoding UTF8 "$HOME\\secrets\\common.env"
```

If you are using an IAM role instead of access keys, omit the two AWS key lines.

## 5. Start the app

### Docker Compose

`docker-compose.yml` already points at `~/secrets/common.env`.

Start it with:

```powershell
docker compose up --build
```

### Local Python

`app.py` now also loads `~/secrets/common.env` automatically.

Start it with:

```powershell
.\\venv\\Scripts\\python.exe app.py
```

## 6. Optional one-time SQLite import

If you want to import the old `progress.db` once, add this to `common.env` before first startup:

```env
SQLITE_MIGRATION_PATH=progress.db
```

For a container where the database file lives inside the image, use its container path instead.

## 7. Verify the connection

When the app starts successfully, it should be able to:

- connect to DynamoDB in `AWS_REGION`
- create missing tables if the identity allows it
- read and write students and progress records

If you want to verify from the shell first:

```powershell
aws dynamodb list-tables --region us-east-1
```

## 8. Local DynamoDB alternative

If you want to test without AWS, run DynamoDB Local and add:

```env
DYNAMODB_ENDPOINT_URL=http://localhost:8000
```

Then the app will talk to the local endpoint instead of AWS.
