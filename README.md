# sight-words AWS migration

## Architecture choice
This codebase is a stateless Flask app with no background workers and short request/response interactions, so it is a good fit for **AWS Lambda (container image) + Function URL + DynamoDB**.

## Runtime and app startup
- Language: Python 3.12
- Framework: Flask
- Local startup: `python -m flask run --host=0.0.0.0 --port=8000`
- Lambda entrypoint: `lambda_handler.handler`

## DynamoDB data model
Two on-demand tables:

1. `sight_words_students`
   - Partition key: `student_id` (Number)
   - Item attributes: `name`, `pin`
   - Special metadata item: `student_id = 0`, `next_student_id`

2. `sight_words_progress`
   - Partition key: `student_id` (Number)
   - Sort key: `word` (String)
   - Attributes: `level`, `correct`, `attempts`, `last_seen`, `status`, `next_review`

### Query/update patterns supported
- List students (`scan`) for low traffic.
- Get student by id (`get_item`).
- Verify/update pin (`get_item`/`update_item`).
- Get one word progress (`get_item`).
- Get all progress for one student (`query` by `student_id`).
- Upsert progress on every attempt (`put_item`).

## Required environment variables
- `OPENAI_API_KEY` (required)
- `AWS_REGION` (default: `us-east-1`)
- `DDB_STUDENTS_TABLE` (default: `sight_words_students`)
- `DDB_PROGRESS_TABLE` (default: `sight_words_progress`)
- `DDB_ENDPOINT_URL` (optional; use for DynamoDB Local only)

## AWS deployment (Lambda + Function URL + ECR)
Set these first:

```bash
AWS_REGION=us-east-1
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REPO_NAME=sight-words
IMAGE_TAG=v1
FUNC_NAME=sight-words
ROLE_NAME=sight-words-lambda-role
```

### 1) Create ECR repo
```bash
aws ecr create-repository \
  --repository-name "$REPO_NAME" \
  --image-scanning-configuration scanOnPush=true \
  --region "$AWS_REGION"
```

### 2) Login Docker to ECR
```bash
aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
```

### 3) Build + push Lambda image
```bash
docker build -t "$REPO_NAME:$IMAGE_TAG" .
docker tag "$REPO_NAME:$IMAGE_TAG" "$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO_NAME:$IMAGE_TAG"
docker push "$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO_NAME:$IMAGE_TAG"
```

### 4) Create DynamoDB tables
```bash
aws dynamodb create-table \
  --table-name sight_words_students \
  --attribute-definitions AttributeName=student_id,AttributeType=N \
  --key-schema AttributeName=student_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region "$AWS_REGION"

aws dynamodb create-table \
  --table-name sight_words_progress \
  --attribute-definitions AttributeName=student_id,AttributeType=N AttributeName=word,AttributeType=S \
  --key-schema AttributeName=student_id,KeyType=HASH AttributeName=word,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --region "$AWS_REGION"
```

### 5) Create IAM role for Lambda
```bash
aws iam create-role \
  --role-name "$ROLE_NAME" \
  --assume-role-policy-document file://infra/lambda-trust-policy.json

aws iam attach-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name sight-words-ddb \
  --policy-document file://infra/lambda-ddb-policy.json
```

### 6) Create Lambda from image
```bash
aws lambda create-function \
  --function-name "$FUNC_NAME" \
  --package-type Image \
  --code ImageUri="$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO_NAME:$IMAGE_TAG" \
  --role "arn:aws:iam::$ACCOUNT_ID:role/$ROLE_NAME" \
  --memory-size 512 \
  --timeout 30 \
  --environment "Variables={OPENAI_API_KEY=REPLACE_ME,AWS_REGION=$AWS_REGION,DDB_STUDENTS_TABLE=sight_words_students,DDB_PROGRESS_TABLE=sight_words_progress}" \
  --region "$AWS_REGION"
```

### 7) Enable public HTTPS with Function URL
```bash
aws lambda create-function-url-config \
  --function-name "$FUNC_NAME" \
  --auth-type NONE \
  --cors '{"AllowOrigins":["*"],"AllowMethods":["*"],"AllowHeaders":["*"]}' \
  --region "$AWS_REGION"
```

### 8) Future deployments
```bash
docker build -t "$REPO_NAME:$IMAGE_TAG" .
docker tag "$REPO_NAME:$IMAGE_TAG" "$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO_NAME:$IMAGE_TAG"
docker push "$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO_NAME:$IMAGE_TAG"

aws lambda update-function-code \
  --function-name "$FUNC_NAME" \
  --image-uri "$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO_NAME:$IMAGE_TAG" \
  --region "$AWS_REGION"
```

## IAM policy files used above
- `infra/lambda-trust-policy.json`
- `infra/lambda-ddb-policy.json`

## SQLite -> DynamoDB migration
Script: `scripts/migrate_sqlite_to_dynamodb.py`

Example (AWS DynamoDB):
```bash
python scripts/migrate_sqlite_to_dynamodb.py \
  --sqlite-path /path/to/progress.db \
  --region us-east-1 \
  --students-table sight_words_students \
  --progress-table sight_words_progress
```

Example (DynamoDB Local):
```bash
python scripts/migrate_sqlite_to_dynamodb.py \
  --sqlite-path /path/to/progress.db \
  --region us-east-1 \
  --ddb-endpoint-url http://localhost:8001 \
  --students-table sight_words_students \
  --progress-table sight_words_progress
```

Validation checks:
- Script prints migrated row counts.
- Compare counts manually:
  - SQLite: `SELECT COUNT(*) FROM students;` and `SELECT COUNT(*) FROM word_progress;`
  - DynamoDB: scan counts from both tables.

## Local run
### Option 1: Python (against real AWS DynamoDB)
```bash
export OPENAI_API_KEY=...
export AWS_REGION=us-east-1
export DDB_STUDENTS_TABLE=sight_words_students
export DDB_PROGRESS_TABLE=sight_words_progress
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m flask run --host=0.0.0.0 --port=8000
```

### Option 2: Docker Compose + DynamoDB Local
```bash
docker compose up --build
```
Then create tables in local DynamoDB:
```bash
aws dynamodb create-table \
  --table-name sight_words_students \
  --attribute-definitions AttributeName=student_id,AttributeType=N \
  --key-schema AttributeName=student_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --endpoint-url http://localhost:8001 \
  --region us-east-1

aws dynamodb create-table \
  --table-name sight_words_progress \
  --attribute-definitions AttributeName=student_id,AttributeType=N AttributeName=word,AttributeType=S \
  --key-schema AttributeName=student_id,KeyType=HASH AttributeName=word,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --endpoint-url http://localhost:8001 \
  --region us-east-1
```

## Main flow smoke test
- Open `/`
- Create/select a student
- Start lesson (PIN prompt only if set)
- Complete word clicks
- Open `/teacher?student_id=<id>` and verify progress stats update

## Post-migration checklist
- Read path works: `/`, `/teacher`, `/api/progress`
- Write path works: student creation, PIN update, record progress
- Function URL reachable and HTTPS works
- CloudWatch logs show no DynamoDB permission/runtime errors
- Lambda environment variables are set correctly
- Migration row counts match source SQLite DB
- App handles OpenAI or DynamoDB errors gracefully (HTTP error + logs)
