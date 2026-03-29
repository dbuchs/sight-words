param(
    [string]$Region = "us-east-1",
    [string]$StudentsTable = "sight_words_students",
    [string]$ProgressTable = "sight_words_progress",
    [string]$MetaTable = "sight_words_meta"
)

$ErrorActionPreference = "Stop"

Write-Host "Creating DynamoDB tables in $Region using on-demand billing..."

$studentsGsiJson = @(
    @{
        IndexName = "name-index"
        KeySchema = @(
            @{
                AttributeName = "name"
                KeyType = "HASH"
            }
        )
        Projection = @{
            ProjectionType = "ALL"
        }
    }
) | ConvertTo-Json -Compress

aws dynamodb create-table `
  --region $Region `
  --table-name $StudentsTable `
  --attribute-definitions `
    AttributeName=id,AttributeType=N `
    AttributeName=name,AttributeType=S `
  --key-schema `
    AttributeName=id,KeyType=HASH `
  --billing-mode PAY_PER_REQUEST `
  --global-secondary-indexes `
    $studentsGsiJson

aws dynamodb wait table-exists --region $Region --table-name $StudentsTable

aws dynamodb create-table `
  --region $Region `
  --table-name $ProgressTable `
  --attribute-definitions `
    AttributeName=student_id,AttributeType=N `
    AttributeName=word,AttributeType=S `
  --key-schema `
    AttributeName=student_id,KeyType=HASH `
    AttributeName=word,KeyType=RANGE `
  --billing-mode PAY_PER_REQUEST

aws dynamodb wait table-exists --region $Region --table-name $ProgressTable

aws dynamodb create-table `
  --region $Region `
  --table-name $MetaTable `
  --attribute-definitions `
    AttributeName=key,AttributeType=S `
  --key-schema `
    AttributeName=key,KeyType=HASH `
  --billing-mode PAY_PER_REQUEST

aws dynamodb wait table-exists --region $Region --table-name $MetaTable

Write-Host "Done."
