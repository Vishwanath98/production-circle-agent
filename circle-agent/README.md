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

## External Circle MCP

The default `mcp_servers.json` starts a deterministic local stdio server. To
keep those risk tools and also exercise a real external MCP integration, use
Circle's official Streamable HTTP server with the additive configuration:

| Server | Transport | Tools | External traffic |
|---|---|---:|---:|
| `circle-risk` | Local stdio | 3 | No |
| `circle-docs` | Streamable HTTP | 4 | Yes |

The external tools search Circle documentation, return product summaries, list
available SDK resources, and retrieve SDK resource details. They are useful for
current product capabilities, supported networks, and implementation guidance.
They do not read wallets or execute transactions.

The external configuration is optional so the normal test suite and default
local setup remain deterministic. Enable it with `CIRCLE_MCP_CONFIG`:

```bash
PYTHONPATH=agent-spine:circle-agent \
  LLM_PROVIDER=openai \
  OPENAI_BASE_URL=http://127.0.0.1:1234/v1 \
  OPENAI_MODEL=local-model \
  CIRCLE_MCP_CONFIG=circle-agent/mcp_servers.external.json \
  .venv/bin/python circle-agent/serve.py
```

Use a tool-capable model for normal model-driven selection of the external MCP
tools. `LLM_PROVIDER=fake` keeps tests offline but does not select documentation
tools from natural-language questions.

## Full testnet and external MCP

Keep credentials in the ignored `.env.local` file. The application does not
load that file automatically; source it in the shell before starting the
server.

```bash
export LLM_PROVIDER=openai
export OPENAI_BASE_URL=http://127.0.0.1:1234/v1
export OPENAI_MODEL=local-model
export OPENAI_API_KEY=local-development

export CIRCLE_MCP_CONFIG=circle-agent/mcp_servers.external.json
export CIRCLE_API_HOST=https://api.circle.com
export CIRCLE_API_KEY=TEST_REPLACE
export CIRCLE_ENTITY_SECRET=REPLACE
export CIRCLE_TESTNET_USDC_TOKEN_ID=REPLACE
export CIRCLE_TESTNET_DESTINATION_ALLOWLIST=0xREPLACE
```

The seeded `wallet-treasury` is a simulator record. Map it to an existing
Circle developer-controlled testnet wallet before using `full-testnet`:

```bash
sqlite3 .local/data/circle.sqlite "
UPDATE wallets
SET provider = 'circle-testnet',
    provider_wallet_id = 'REPLACE_CIRCLE_WALLET_ID',
    address = 'REPLACE_WALLET_ADDRESS',
    chain = 'base',
    asset = 'USDC',
    updated_at = datetime('now')
WHERE organization_id = 'org-acme'
  AND wallet_id = 'wallet-treasury';
"
```

Load the configuration and start the agent:

```bash
set -a
source .env.local
set +a

PYTHONPATH=agent-spine:circle-agent .venv/bin/python circle-agent/serve.py
```

Open `http://127.0.0.1:8086`, sign in with the `org-acme` requester token, and
select `full-testnet`. Use the matching reviewer token to approve a transfer.
The resulting run can call both the external Circle MCP server and the Circle
Wallet HTTPS API. There is no mainnet profile or automatic simulator fallback.

## Capture and replay proxy

Start Hoverfly or another HTTP capture/replay proxy, then export its proxy URL
before starting the agent. For HTTPS interception, configure the Python runtime
to trust the proxy's generated CA certificate.

```bash
export HTTP_PROXY=http://127.0.0.1:8500
export HTTPS_PROXY=http://127.0.0.1:8500
export SSL_CERT_FILE=/absolute/path/to/hoverfly-ca.pem
export REQUESTS_CA_BUNDLE=/absolute/path/to/hoverfly-ca.pem
```

The proxy can capture:

- Circle MCP Streamable HTTP initialization, tool discovery, calls, and results.
- Circle Wallet balance lookup, transfer submission, and transaction lookup.
- Circle webhook public-key lookup.

The proxy cannot capture the local `circle-risk` stdio messages. Incoming
Circle webhooks are also outside an outbound proxy and should be recorded as
separate inbound fixtures. Redact authorization headers, API keys, entity-secret
material, and encrypted signing material before sharing captures. Normalize
request IDs and idempotency values when strict replay matching is not required.
