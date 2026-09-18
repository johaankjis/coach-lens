# AWS-2 internal implementation plan

1. Keep M2 normalization, statistics, local evidence, and M3 review contracts unchanged. Only the strict three-workbook local loader may mint trusted ResultsCX provenance.
2. Prepare each real signal locally from its M3 evidence bundle and matching M2 evaluations. Use deterministic, fail-closed text decisions; retain raw evidence and source lineage locally.
3. Build a separate, explicit Bedrock wire projection with opaque references and deterministic coverage. Bind the real reasoner to the trusted in-memory population and verify the provider view against it before invocation.
4. Resolve Bedrock references through the local map, preserving strict AWS-1 output validation and M4 awaiting-review state.
5. Add adversarial privacy and regression tests, document limitations, run full repository validation and hygiene checks, then commit on the requested branch.
