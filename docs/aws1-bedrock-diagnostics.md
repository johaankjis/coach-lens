# AWS-1: Bedrock diagnostic provider

AWS-1 implements only the M3 diagnostic reasoner. M2 produces deterministic QA signals and coverage. M3 builds and validates the evidence bundle, then the Bedrock adapter projects an allowlisted synthetic payload, calls Bedrock Runtime `Converse`, validates the JSON response, resolves opaque citations locally, and returns a normal M3 hypothesis. The existing M3 human Approve / Reject / Revise workflow follows. The adapter uses `boto3` because it is the AWS SDK that supplies Bedrock Runtime `Converse` and the normal AWS credential provider chain; no credentials are stored here.

`COACHLENS_BEDROCK_ENABLED` defaults to `false`. When true, the normal API and explicit ResultsCX demo install a `BedrockReasoner` and `/diagnostics/mode` reports `diagnostic_provider: provider` from the installed object. The invocation region defaults to `us-east-1`, and the system-defined inference profile defaults to `global.anthropic.claude-sonnet-4-6`. Override with `COACHLENS_BEDROCK_REGION` and `COACHLENS_BEDROCK_MODEL_ID`. Obtain temporary AWS credentials through the normal SDK environment, profile, or role chain outside Git. Never put credential values in `.env`, source, logs, or documentation.

## Privacy boundary

The selected **global** inference profile may route outside `us-east-1`. The existing local M3 provider view uses known-name redaction only; it is not anonymized and may contain PHI or PII in evaluator feedback. AWS-1 therefore refuses remote invocation by default, including when Bedrock is enabled with real ResultsCX records. An explicit synthetic-only switch exists solely in the smoke entry point. The Bedrock payload includes a synthetic criterion label, domain, deterministic fail and evaluated result counts, failure rate, evaluations containing the criterion, total loaded evaluations, feedback count, and structured per-row pass/score facts. It excludes raw feedback, free-text answers, names, local evaluation and evidence IDs, filenames, paths, sheets, and `SourceLineage`. Opaque `SIGNAL-001` and `EVID-###` references are mapped back to local M3 IDs after validation. No free-text sanitization or HIPAA/PHI detection is claimed. The local reviewer evidence route retains its existing confidential evidence behavior.

Real ResultsCX remote diagnosis requires a separately reviewed provider-safety policy and tests. Enabling the setting alone does not permit it. Do not use the synthetic switch with workbooks or normalized real records.

## Synthetic smoke

From the repository root, install the API dependencies, supply temporary AWS credentials through the normal SDK chain, and run:

```sh
COACHLENS_BEDROCK_ENABLED=true python scripts/run_bedrock_synthetic_smoke.py
```

The script rejects a configured `COACHLENS_API_DIAGNOSTIC_EVALUATIONS_PATH` and builds four synthetic evaluations in memory. It invokes Bedrock once, validates a normal `DiagnosticRecord`, and prints only a status, cause category, confidence, reference count, provider identifiers, and aggregate coverage. It does not print model reasoning, raw evidence, credentials, or request headers. The caller needs permission to invoke the selected inference profile. The normal API does not enable the synthetic switch.

Malformed, semantically invalid, or uncited model output fails with a sanitized 502 response and stores no diagnosis. AWS errors also become a sanitized 502; there is no fixture fallback. A privacy-blocked real-data invocation returns 502 before an AWS client is created. The provider metadata records Amazon Bedrock, inference profile, invocation region, a request ID when available, UTC generation time, and `provider` generation mode. The diagnosis remains `awaiting_review` until a human acts.

AWS-1 does not implement intervention or training providers, evidence or solution validators, alignment guard, outcome evaluation, AgentCore, S3, DynamoDB, Lambda/API Gateway, voice, deployment, authentication, or changes to scoring, normalization, and human validation.
