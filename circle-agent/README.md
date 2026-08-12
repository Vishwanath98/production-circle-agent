# Circle production lab

This folder is the local, testnet-only implementation of the production Circle
agent design. It replaces separate base/RAG/MCP workflows with one LangGraph
and explicit capability profiles.

## Start locally

Run from the repository root with Python 3.11:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e agent-spine -r circle-agent/requirements.txt
PYTHONPATH=agent-spine:circle-agent .venv/bin/python circle-agent/setup_local.py
PYTHONPATH=agent-spine:circle-agent LLM_PROVIDER=fake .venv/bin/python circle-agent/serve.py
```

`setup_local.py` prints four one-time local credentials: requester and reviewer
identities for two organizations. Open `http://127.0.0.1:8086`, sign in with a
credential, and use a requester token to create a transfer. Sign in as that
organization's reviewer to decide the pending approval.
Rerunning setup retains existing credential hashes and does not mint extra
tokens. Use `--rotate-credentials` intentionally if the printed values were
lost or exposed.

Local state is written under `.local/data/`, which is ignored by Git. The
server binds only to loopback unless `ALLOW_NON_LOOPBACK=true` is set
intentionally.

## Profiles

| Profile | Provider | RAG | MCP 2.0 | x402 |
|---|---|---:|---:|---:|
| `core-sim` | Deterministic simulator | No | No | No |
| `rag-sim` | Deterministic simulator | Yes | No | No |
| `mcp-sim` | Deterministic simulator | No | Yes | No |
| `full-sim` | Deterministic simulator | Yes | Yes | No |
| `full-testnet` | Circle SDK testnet | Yes | Yes | No |
| `x402-testnet` | Circle SDK testnet | Yes | Yes | Yes |

There is no mainnet profile. A Circle API failure never falls back to the
simulator. Every financial effect uses a durable action envelope, policy
decision, authorized approval, exact action-digest verification, atomic claim,
and provider idempotency key.

## Useful commands

```bash
# Full automated suite (the HTTP integration test needs localhost bind access)
PYTHONPATH=agent-spine:circle-agent .venv/bin/python -m unittest discover -s agent-spine/tests -v
PYTHONPATH=agent-spine:circle-agent .venv/bin/python -m unittest discover -s circle-agent/tests -v

# Compile check
PYTHONPYCACHEPREFIX=/tmp/circle-pycache PYTHONPATH=agent-spine:circle-agent \
  .venv/bin/python -m compileall -q agent-spine/agent_spine circle-agent

# API smoke with a setup token
curl -s http://127.0.0.1:8086/healthz
curl -s http://127.0.0.1:8086/chat \
  -H 'Authorization: Bearer dev_...' -H 'Content-Type: application/json' \
  -d '{"thread_id":"demo","profile":"core-sim","message":"{\"action\":\"balance\"}"}'
```

The API contract is in [`../docs/api/openapi.yaml`](../docs/api/openapi.yaml).
The build map, security model, ADRs, testing gates, and remaining production
promotion work are under [`../docs/adlc/`](../docs/adlc/).
