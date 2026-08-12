# Onboarding production lab

The default `serve.py` runs the tenant-safe unified Onboarding graph. Capability
profiles reuse the same graph and production execution path.

```bash
.venv/bin/pip install -e agent-spine -r onboarding-agent/requirements.txt
PYTHONPATH=agent-spine:onboarding-agent .venv/bin/python onboarding-agent/setup_local.py
PYTHONPATH=agent-spine:onboarding-agent LLM_PROVIDER=fake \
  .venv/bin/python onboarding-agent/serve.py
```

Use the printed applicant token with `POST /chat`. Eligible applications pause
with `approval_required`; use the reviewer token with
`POST /api/v1/approvals/{approval_id}/decisions`. The exact application action
digest is revalidated before the account is provisioned.
Rerunning setup retains existing credentials. Pass `--rotate-credentials` to
revoke them and print replacements.

```bash
curl -s http://127.0.0.1:8087/chat \
  -H 'Authorization: Bearer dev_...' -H 'Content-Type: application/json' \
  -d '{"thread_id":"app-1","profile":"core-sim","message":"{\"action\":\"submit\",\"business_name\":\"Acme Logistics\",\"business_type\":\"LLC\",\"email\":\"ops@acme.example\",\"phone\":\"+15555550100\",\"use_case\":\"Transactional delivery alerts\",\"monthly_volume\":50000}"}'
```

Profiles are `core-sim`, `rag-sim`, `mcp-sim`, and `full-sim`. Project-owned
model affordances are native `@tool` functions. RAG, MCP 2.0, durable state,
RBAC, approval, audit, and tenant boundaries reuse agent-spine.
