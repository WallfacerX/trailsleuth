# Synthetic ingestion: deployment and operations

This guide is a handoff for a future manual deployment. Milestone 2 supplies code, offline tests, a Lambda package builder, and validated Terraform configuration. **It has not deployed resources or verified end-to-end AWS behavior.** Commands below that apply Terraform, upload data, redrive messages, or delete data change your AWS account; run them only when you choose to deploy or clean up.

## 1. Tools and credentials

Use Python 3.12, pip, Terraform 1.6 or later (below 2.0), AWS CLI v2, and jq. Python 3.11 remains supported for the local CLI/tests. With Homebrew on macOS:

```sh
brew install python@3.12 awscli jq
brew tap hashicorp/tap
brew install hashicorp/tap/terraform
python3.12 --version
aws --version
terraform version
```

Follow the official [AWS CLI installation guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) or [Terraform installation guide](https://developer.hashicorp.com/terraform/install) on other platforms.

Prefer short-lived credentials. If your account has IAM Identity Center configured, create and log in to a named profile:

```sh
aws configure sso --profile trailsleuth-dev
aws sso login --profile trailsleuth-dev
export AWS_PROFILE=trailsleuth-dev
export AWS_REGION='REPLACE_WITH_REGION'
aws sts get-caller-identity --query '{Account:Account,Arn:Arn}'
aws configure list
aws lambda get-account-settings --query AccountLimit
```

The [SSO profile guide](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html) explains the prompts. An account without Identity Center can use an administrator-provided assume-role or other temporary-credential profile; do not create root access keys for this project. Existing credential environment variables can override a profile, so verify the identity actually returned by STS. Do not copy credentials into Terraform, fixtures, the repository, or chat.

The intended account and Region must match the variable file below. Confirm the account has enough Lambda concurrency quota to reserve two executions while retaining AWS's required unreserved capacity. New accounts may have reduced quotas; request a quota adjustment if necessary instead of mismatching event-source and function concurrency.

The deployment identity needs permission to manage this stack's S3, SQS, Lambda, IAM role/policy (including scoped `iam:PassRole`), logs, and alarms. This is separate from the much narrower Lambda execution role. The module does not grant permissions to its deployer. Review organizational SCPs, permission boundaries, resource names, and deployment permissions before planning.

## 2. Build and validate locally

From the repository root:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m trailsleuth detect sample_data/cloudtrail_events.json
python -m pytest
python -m ruff check .
python -m ruff format --check .
python scripts/build_lambda.py
python scripts/check_lambda_artifact.py
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform init -backend=false -input=false -lockfile=readonly
terraform -chdir=infra/terraform validate
```

The builder installs the complete pinned SDK dependency closure from `requirements-lambda.txt`, selects Python 3.12/Linux ARM64-compatible wheels, and copies the project into `build/lambda/ingestion.zip`. These dependencies are currently pure Python. Sorted ZIP entries and fixed timestamps make repeat builds stable. Build directories and archives stay out of Git. If dependencies change, resolve and review the full compatible set, rebuild, and repeat isolated import verification; introducing native extensions would also require testing in an Amazon Linux ARM64 environment.

The import check extracts the ZIP outside the checkout and runs Python with isolated mode and site-packages disabled. It imports both the packaged handler and SDK and processes a test notification with no AWS client. This catches packaging errors, but it does not emulate the entire Lambda environment.

Terraform references the ZIP path and its content hash, so code changes become visible in a future plan after rebuilding. It never runs the build for you. `init -backend=false` and `validate` need no AWS credentials; provider/package downloads need network access. See [Terraform basics](terraform-basics.md) for the distinction between a provider, configuration, lock file, and state.

## 3. Configure and review a plan

```sh
cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
```

Edit the ignored file. Replace every placeholder: set `expected_account_id` to the STS account, `aws_region` to your chosen Region, and short lowercase project/environment names. Project names allow 1–16 characters and environment names 1–8, starting with a letter and otherwise containing letters, digits, or hyphens. Use nonpersonal tag labels. The AWS provider's `allowed_account_ids` setting refuses a different account.

There is no remote backend yet. This guide assumes one operator using local state on an encrypted disk with a protected backup. Keep state and saved plans private and outside Git. Do not use CI or another workstation to apply independently against the same resources; configure a secure remote backend with locking before shared deployment work.

```sh
terraform -chdir=infra/terraform init -input=false -lockfile=readonly
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform plan -out=review.tfplan
terraform -chdir=infra/terraform show -no-color review.tfplan
```

A plan may read AWS APIs. Validation alone does not test credentials, quotas, resource-name availability, service delivery, or IAM behavior. Review the expected account/Region, the two bucket names, retention, IAM statements, Lambda package hash, and changes listed below. Investigate any unexpected deletion or replacement. Rebuild/replan after code or configuration changes; do not reuse a stale plan. Saved plans include potentially sensitive configuration and are ignored.

A future apply creates:

| Resource | Purpose and defaults |
| --- | --- |
| Input S3 bucket | Private, SSE-S3 encrypted, versioned; `incoming/` uploads notify SQS. No automatic object expiration. |
| Results S3 bucket | Separate private, SSE-S3 encrypted bucket; unversioned results avoid duplicate output versions and notification loops. No notifications. |
| SQS queue and DLQ | Standard queues using SSE-SQS; source retention 4 days, DLQ retention 14 days, max receive count 5. |
| Lambda and event source mapping | Python 3.12 ARM64, 512 MB, 60-second timeout, batch size 1, no batch window, maximum/reserved concurrency 2. |
| IAM role and inline policy | Exact queue/log resources, versioned input reads, and result-prefix writes only. |
| CloudWatch log group | Explicit 14-day retention. |
| Two CloudWatch alarms | Lambda Errors and visible DLQ messages, each alarming at at least one in a 60-second period. No notification actions. |
| Bucket/queue configuration and policies | Public access blocks, ownership controls, encryption, input versioning, HTTPS-only bucket policies, notification permission, and restricted DLQ source. |

S3 and SQS use service-managed encryption, avoiding customer KMS key cost and key-policy complexity. Buckets have `force_destroy = false`; Terraform will not empty them for you. S3 notifications are permitted only for the specified bucket and account. The DLQ accepts redrive from the intended source queue only. There is no VPC, NAT gateway, real CloudTrail trail, Bedrock integration, or API.

The 360-second visibility timeout gives a 60-second function six times its timeout, with no added batch window. Maximum event-source concurrency and reserved function concurrency both equal two, preventing an intentional mismatch that could cause throttling. `ReportBatchItemFailures` lets successfully processed messages be acknowledged while failed messages retry.

Lambda permissions contain wildcards only for object names under `incoming/` and `results/v1/`, and log streams within the one log group. Those names vary per upload/invocation. The HTTPS bucket policy uses `Principal: "*"` and `s3:*` only in a **Deny**, not an access grant; AWS service principals are exempt from this transport check because service request context can redact network attributes. Lambda has no bucket-list, object-delete, DLQ, KMS, or account-wide permissions.

Alarm state is visible in CloudWatch, but there are no SNS topics, email recipients, or paging integrations. Handled partial batch failures do not necessarily raise the Lambda Errors metric; inspect structured failure logs and the DLQ too. Add notification routing deliberately before relying on unattended monitoring.

## 4. Apply later and upload a fixture

Only after reviewing the saved plan and choosing to deploy:

```sh
terraform -chdir=infra/terraform apply review.tfplan
```

Applying a saved plan executes its approved changes without another plan review prompt. Keep the same verified profile and Region. After a successful apply, read outputs rather than copying account-specific names into scripts:

```sh
INPUT_BUCKET=$(terraform -chdir=infra/terraform output -raw input_bucket_name)
RESULTS_BUCKET=$(terraform -chdir=infra/terraform output -raw results_bucket_name)
INPUT_PREFIX=$(terraform -chdir=infra/terraform output -raw input_prefix)
RESULTS_PREFIX=$(terraform -chdir=infra/terraform output -raw results_prefix)
QUEUE_URL=$(terraform -chdir=infra/terraform output -raw queue_url)
QUEUE_ARN=$(terraform -chdir=infra/terraform output -raw queue_arn)
DLQ_URL=$(terraform -chdir=infra/terraform output -raw dlq_url)
DLQ_ARN=$(terraform -chdir=infra/terraform output -raw dlq_arn)
LOG_GROUP=$(terraform -chdir=infra/terraform output -raw log_group_name)
MAPPING_UUID=$(terraform -chdir=infra/terraform output -raw event_source_mapping_uuid)
export AWS_REGION=$(terraform -chdir=infra/terraform output -raw aws_region)
aws sts get-caller-identity --query Account --output text
terraform -chdir=infra/terraform output -raw account_id
```

Check the two account values agree. AWS recommends waiting **15 minutes after first enabling bucket versioning** before PUT/DELETE operations to allow propagation. See [S3 versioning behavior](https://docs.aws.amazon.com/AmazonS3/latest/userguide/versioning-workflows.html). After that interval, upload only synthetic data:

```sh
INPUT_KEY="${INPUT_PREFIX}demo/cloudtrail_events.json"
SOURCE_VERSION=$(aws s3api put-object \
  --bucket "$INPUT_BUCKET" --key "$INPUT_KEY" \
  --body sample_data/cloudtrail_events.json --content-type application/json \
  --query VersionId --output text)
printf '%s\n' "$SOURCE_VERSION"
```

The version must not be empty, `None`, or `null`. The handler deliberately rejects absent/immutable-version-less notifications: reading the latest object could process the wrong upload after a delay. Gzip input is also supported; create a local `.json.gz` file and upload it under `incoming/` the same way. The handler limits both downloaded input (5 MiB) and decompressed content (20 MiB), and rejects malformed data.

## 5. Find and inspect the result

Delivery is asynchronous. Wait briefly, then compute the exact result key with the same helper used by Lambda:

```sh
RESULT_KEY=$(python -c 'import sys; from trailsleuth.ingestion import result_key; print(result_key(*sys.argv[1:]))' \
  "$INPUT_BUCKET" "$INPUT_KEY" "$SOURCE_VERSION")
aws s3 ls "s3://$RESULTS_BUCKET/$RESULTS_PREFIX" --recursive
aws s3 cp "s3://$RESULTS_BUCKET/$RESULT_KEY" - | python -m json.tool
aws logs tail "$LOG_GROUP" --since 10m
```

If the result is not yet available, inspect logs/queues and retry the read; do not infer failure or success from a single immediate lookup. For the supplied fixture, expect five normalized events and two findings (`TS-001`, `TS-002`), with the denied StopLogging event preserved but not reported as a successful change. The result includes original bucket/key/version and event IDs. Logs record message ID, record index, result key/counts on success, and bounded failure categories; they do not dump CloudTrail records or exception text.

Repeat the upload command using the same `INPUT_KEY`. S3 returns a **new version ID**, and computing `RESULT_KEY` again gives a new result even for identical bytes. To see both versions:

```sh
aws s3api list-object-versions --bucket "$INPUT_BUCKET" --prefix "$INPUT_KEY"
```

A duplicate delivery of the **same** version rewrites the same result bytes for the same processor version. This is idempotent result writing, not exactly-once processing: S3/SQS can deliver repeatedly, computation and PUT costs may repeat, and results do not deduplicate events across separate uploads. Each object produces one atomic S3 PUT containing events and findings, so no completion marker can precede durable output. For a multi-object message, a successful write followed by a failed one causes that message to retry; already-written results safely converge. Versioned reprocessing for changed rules/schemas is a future design decision.

## 6. Investigate failures and retry safely

```sh
aws sqs get-queue-attributes --queue-url "$QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible
aws sqs get-queue-attributes --queue-url "$DLQ_URL" \
  --attribute-names ApproximateNumberOfMessages
aws logs tail "$LOG_GROUP" --since 1h
```

Malformed input, version mismatches, read failures, and write failures return failed SQS message IDs. Repeated failures eventually reach the DLQ; this takes time and is not an immediate operation. Whole-invocation failures such as timeouts also retry. Queue retention is finite, so investigate rather than treating the DLQ as permanent storage.

To inspect a DLQ message, the following receive call temporarily hides it for 30 seconds and increments its receive count; it does not delete it:

```sh
aws sqs receive-message --queue-url "$DLQ_URL" \
  --max-number-of-messages 1 --visibility-timeout 30 --wait-time-seconds 5
```

Fix the cause first. For a transient IAM/service problem, repair the configuration, rebuild/review/apply if needed, then redrive slowly. A malformed immutable object cannot be fixed by overwriting the same key: the old notification still refers to its old version. Upload corrected synthetic data as a new version; preserve/investigate the old failure and delete its DLQ message only after deliberately resolving it. Do not blindly redrive poison messages or purge the queue.

For a verified transient problem, an authorized operator can move DLQ messages back to the source:

```sh
TASK_HANDLE=$(aws sqs start-message-move-task \
  --source-arn "$DLQ_ARN" --destination-arn "$QUEUE_ARN" \
  --max-number-of-messages-per-second 1 --query TaskHandle --output text)
aws sqs list-message-move-tasks --source-arn "$DLQ_ARN"
# If failures recur, stop further movement; already-moved messages remain in flight:
# aws sqs cancel-message-move-task --task-handle "$TASK_HANDLE"
```

These operator permissions are not granted to Lambda. AWS's [DLQ redrive guide](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-configure-dead-letter-queue-redrive.html) lists the needed receive/delete/get-attributes/start-move permissions on the DLQ and send permission on the destination. Watch logs, alarms, results, and both queues during recovery.

## 7. Cleanup later

Cleanup is destructive. Save any evidence you intend to retain, stop uploads, and disable consumption before emptying buckets. This guide assumes only the synthetic demo stack. Disabling the mapping manually creates temporary Terraform drift; a future apply would restore it unless configuration also changes.

```sh
aws lambda update-event-source-mapping --uuid "$MAPPING_UUID" --no-enabled
aws lambda get-event-source-mapping --uuid "$MAPPING_UUID" --query State
```

Wait until the mapping is `Disabled` and any in-flight invocation has finished (at least one 60-second function timeout after disabling). Do not redrive messages during cleanup. This prevents result writes racing bucket deletion.

Deleting a versioned object by key usually creates a delete marker and leaves its versions behind. `aws s3 rm --recursive` alone does not empty the versioned input bucket. List **both versions and delete markers**, review the generated deletion batch, then explicitly remove up to 1,000 at a time:

```sh
CLEANUP_DIR=$(mktemp -d)
aws s3api list-object-versions --bucket "$INPUT_BUCKET" --output json > "$CLEANUP_DIR/versions.json"
jq '{Objects: ([.Versions[]?, .DeleteMarkers[]?] | map({Key,VersionId}) | .[:1000]), Quiet: true}' \
  "$CLEANUP_DIR/versions.json" > "$CLEANUP_DIR/delete.json"
cat "$CLEANUP_DIR/delete.json"
# Only after reviewing this exact batch, and only when Objects is nonempty:
aws s3api delete-objects --bucket "$INPUT_BUCKET" --delete "file://$CLEANUP_DIR/delete.json"
```

Check the response for per-object errors. Repeat the list/build/review/delete steps until both lists are empty. Do not disable AWS CLI pagination when listing. The results bucket is intentionally unversioned, so after reviewing its listing:

```sh
aws s3 ls "s3://$RESULTS_BUCKET/" --recursive
aws s3 rm "s3://$RESULTS_BUCKET/" --recursive
terraform -chdir=infra/terraform plan -destroy -out=cleanup.tfplan
terraform -chdir=infra/terraform show -no-color cleanup.tfplan
# Only after reviewing the saved destruction plan:
terraform -chdir=infra/terraform apply cleanup.tfplan
```

Terraform deletes the queues (including pending messages), Lambda, IAM role/policy, alarms, log group, and empty buckets. Log-group deletion discards remaining logs. `terraform destroy` is the interactive alternative to the saved destruction plan. Keep `force_destroy = false`; it is a useful guard against accidental data loss. Retain the protected state until cleanup succeeds, and remove local temporary review files when no longer needed.

## Costs and limitations

Costs come from S3 requests/storage (including every input version), SQS requests and polling, Lambda duration/invocations, CloudWatch log ingestion/storage, and alarms. Duplicate processing and retries add work. Low concurrency limits throughput, not total spending. Fourteen-day log/DLQ retention is configured; S3 objects do not expire automatically and must be cleaned up. There is no NAT gateway, customer KMS key, Bedrock, or provisioned concurrency cost in this stack.

Set a small AWS Budget appropriate to your account before deployment and check actual usage. **Budget alerts are not hard spending caps** and may arrive after costs accrue; no budget resource or alarm notification routing is created here. Consult [AWS Budgets behavior](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html) and current service pricing rather than assuming the free tier covers the exercise.

Local checks do not prove live delivery, IAM correctness in your account, resource-name availability, quotas, ARM64 Lambda execution, or the alarm/DLQ recovery path. Complete the synthetic AWS verification gate before adding Bedrock. Log contents remain untrusted data; neither rule findings nor future semantic similarity prove malicious activity.

## Official references used

- [S3 notification structure, key encoding, and test events](https://docs.aws.amazon.com/AmazonS3/latest/userguide/notification-content-structure.html)
- [S3 destination policies](https://docs.aws.amazon.com/AmazonS3/latest/userguide/grant-destinations-permissions-to-s3.html)
- [SQS event-source configuration](https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-configure.html) and [concurrency settings](https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-scaling.html)
- [Partial batch failure responses](https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-errorhandling.html)
- [Python ZIP packaging](https://docs.aws.amazon.com/lambda/latest/dg/python-package.html)
- Terraform [S3 notifications](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_notification), [SQS queue](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sqs_queue), [Lambda function](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lambda_function), and [event-source mapping](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lambda_event_source_mapping). Configuration is also validated against the unchanged locked AWS provider 6.68.0 schema.
