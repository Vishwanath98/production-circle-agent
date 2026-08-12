# Test strategy and release gates

## Automated layers

- Foundation unit tests: credentials, context, policy, approvals, redaction,
  idempotency, atomic claim, durable checkpointer, model configuration.
- Circle contract tests: real `BaseTool` schemas, simulator, tenant isolation,
  RAG prefilter, Circle SDK adapter with a fake gateway, webhook cryptography,
  MCP 2.0 transport, HITL interrupt/resume, and HTTP session/API behavior.
- The implementation log preserves the legacy characterization findings; the
  standalone public repository excludes superseded agent implementations so
  static extractors see one authoritative production path.
- Scrimmage end-to-end: run every profile through native `/chat` and OpenAI
  shapes using stable thread IDs and both organizations.

## Adversarial cases to retain

- Same wallet, thread, document, action, and transaction IDs across tenants.
- Forged object IDs and destination-parent changes.
- Prompt asks to ignore policy, reveal another tenant, or call raw execution.
- MCP tool omitted from allowlist, malformed schema, timeout, crash, oversized
  output, and injected instructions.
- RAG corpus includes malicious instructions and cross-tenant near-duplicates.
- Approval has wrong tenant, reviewer role, digest, version, status, or expiry.
- Concurrent approval resumes and repeated provider requests.
- Circle submission times out before response; retry uses the same idempotency.
- Webhook has invalid signature, unknown subscription, duplicate ID/hash,
  out-of-order status, or unknown state.
- Restart occurs during pending approval and during provider submission.

## Current command

```bash
PYTHONPYCACHEPREFIX=/tmp/circle-pycache PYTHONPATH=agent-spine:circle-agent \
  .venv/bin/python -m unittest discover -s agent-spine/tests -v
PYTHONPYCACHEPREFIX=/tmp/circle-pycache PYTHONPATH=agent-spine:circle-agent \
  .venv/bin/python -m unittest discover -s circle-agent/tests -v
PYTHONPYCACHEPREFIX=/tmp/circle-pycache PYTHONPATH=agent-spine:onboarding-agent \
  .venv/bin/python -m unittest discover -s onboarding-agent/tests -v
```

The localhost HTTP integration test may require sandbox permission to bind an
ephemeral loopback port. No test makes a live Circle or mainnet call.

The standalone public export release gate passes all 33 tests: 16 shared
foundation tests, 12 Circle tests, and 5 Onboarding tests.
