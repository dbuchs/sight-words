param(
    [string]$Region = "us-east-1",
    [string]$UserName = "sight-words-vps",
    [string]$PolicyName = "sight-words-dynamodb-access",
    [string]$StudentsTable = "sight_words_students",
    [string]$ProgressTable = "sight_words_progress",
    [string]$MetaTable = "sight_words_meta"
)

$ErrorActionPreference = "Stop"

$accountId = aws sts get-caller-identity --query Account --output text
if (-not $accountId) {
    throw "Could not determine AWS account ID. Run 'aws configure' first."
}

$policyTemplatePath = Join-Path $PSScriptRoot "vps-dynamodb-policy.json"
$policyOutputPath = Join-Path $PSScriptRoot "vps-dynamodb-policy.resolved.json"

$policy = Get-Content $policyTemplatePath -Raw
$policy = $policy.Replace("ACCOUNT_ID", $accountId)
$policy = $policy.Replace("us-east-1", $Region)
$policy = $policy.Replace("sight_words_students", $StudentsTable)
$policy = $policy.Replace("sight_words_progress", $ProgressTable)
$policy = $policy.Replace("sight_words_meta", $MetaTable)
Set-Content -Path $policyOutputPath -Value $policy -Encoding UTF8

Write-Host "Creating IAM policy $PolicyName..."
$policyArn = aws iam create-policy `
  --policy-name $PolicyName `
  --policy-document file://$policyOutputPath `
  --query Policy.Arn `
  --output text

Write-Host "Creating IAM user $UserName..."
aws iam create-user --user-name $UserName | Out-Null

Write-Host "Attaching policy to user..."
aws iam attach-user-policy --user-name $UserName --policy-arn $policyArn

Write-Host "Creating access key for VPS..."
aws iam create-access-key --user-name $UserName
