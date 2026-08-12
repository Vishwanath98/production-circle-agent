# Contributing

Use Python 3.11 and keep changes explicit and easy to debug. Do not add a new
effect path that bypasses authentication, tenant scoping, policy evaluation,
human approval, exact action-digest validation, idempotency, and audit.

Before opening a pull request:

1. Run all three test commands in the root README.
2. Add tenant-isolation and authorization tests for every new data path.
3. Update OpenAPI, JSON Schemas, ADRs, and runbooks when contracts change.
4. Confirm local state, credentials, traces, and generated caches are ignored.
5. Keep mainnet support out of scope unless it receives a separate security
   review and explicit approval.

Do not submit real customer data, credentials, wallet secrets, or production
provider responses in code, fixtures, issues, or pull requests.
