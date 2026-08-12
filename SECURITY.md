# Security policy

Do not report vulnerabilities through a public issue. Use GitHub's private
security-advisory flow for this repository.

Never include API keys, entity secrets, access tokens, private keys, local
database contents, webhook payloads containing customer data, or production
tenant identifiers in a report.

The supported code is the current `main` branch. This repository is a local and
testnet reference implementation; it has no supported mainnet configuration.

The security model, trust boundaries, threat cases, and production-promotion
requirements are documented in
[`docs/adlc/security-and-tenancy.md`](docs/adlc/security-and-tenancy.md) and
[`docs/adlc/operations.md`](docs/adlc/operations.md).
