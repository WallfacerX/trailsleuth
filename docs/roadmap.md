# TrailSleuth roadmap

## Milestone 1 — implemented: local event processing

Synthetic CloudTrail fixtures, normalization with provenance, two deterministic rules, an offline JSON CLI, tests, Ruff, credential-free CI, and Terraform provider/variable configuration. There is no cloud deployment or semantic functionality yet.

## Milestone 2 — planned: ingestion deployment

Add S3 object notifications through SQS to an ingestion Lambda that reuses the local parser and rules. Support CloudTrail gzip objects, retries, duplicate delivery, partial batch failures, and a dead-letter queue. Preserve original object references and event IDs. Add scoped IAM, encryption, retention, a secure Terraform state backend, operational logs, cost controls, and a documented cleanup path. Start with synthetic uploads; configuring real CloudTrail logging is separate work.

Acceptance: a synthetic upload is processed through the queue; replay does not duplicate stored results; failed records are observable and recoverable. Verify current service, Region, and provider support before implementing resources.

## Milestone 3 — planned: embeddings and retrieval

Describe normalized events and embed them with Bedrock Titan Text Embeddings V2. Store embeddings and evidence metadata in S3 Vectors, and embed analyst questions for retrieval. Decide dimensions, distance metric, filtering, batching, idempotency, and retention together. Measure retrieval with known relevant synthetic events before adding generated explanations.

Official documentation confirms [Titan Text Embeddings V2](https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html) and the AWS provider's [S3 Vectors index resource](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3vectors_index). These references establish available building blocks, not account access, chosen Region support, or a deployed integration. Recheck those constraints when implementation begins.

## Milestone 4 — planned: evidence-grounded investigations

Use a Bedrock text model to explain retrieved evidence with original event-ID citations and source references. Require claims to be supported by cited events; distinguish observed facts, hypotheses, and missing context. Return an insufficient-evidence response when appropriate. Verify citations against the retrieved evidence before returning an answer.

Treat log fields, descriptions, and retrieved content as untrusted data. Isolate them from instructions, test prompt-injection attempts, and do not allow evidence text to authorize actions. Semantic similarity and rule severity never establish malicious intent or prove compromise.

## Milestone 5 — planned: authenticated API

Expose a hunt Lambda through API Gateway with authentication and authorization selected for the intended audience. Define who may search which evidence, enforce request limits, and add throttling, audit logs, and safe error responses. Keep credentials out of clients and logs. No frontend is required to demonstrate the API.

## Milestone 6 — planned: evaluation and portfolio polish

Build a labeled synthetic evaluation set including legitimate administrative changes, denied actions, unrelated events, missing context, and malicious-looking log text. Measure retrieval relevance, citation correctness, unsupported claims, false positives, latency, and cost. Publish reproducible results with limitations.

Add a short demo, updated deployed-versus-planned diagrams, design decisions, operational guidance, and a cost/cleanup walkthrough. Preserve an offline path so reviewers can inspect the project without an AWS account. Avoid claims of production readiness until evidence supports them.
