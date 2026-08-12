# ADR 0005: Testnet only and no provider fallback

Status: accepted.

Decision: the lab has simulator and Circle testnet profiles but no mainnet
profile. Circle errors fail closed and are never replaced by simulator results.
x402 supports allowlisted testnet CAIP-2 networks only.

Consequences: simulator behavior is explicit and deterministic. Mainnet
requires a separate reviewed change after production gates pass.
