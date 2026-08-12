# Internal Circle-integration policy — supported chains, limits, controls

This document is the internal operating policy for USDC payments
initiated through this agent. It binds the agent's settlement
decisions and is the authoritative source for the `route_decision`
node when both regulatory documents (01–03) are silent on a question.

## Supported settlement chains

USDC may be settled on the following chains. Settlement on any other
chain must be rejected at the `select_chain_fee` node:

| Chain     | Settlement asset | Min fee (USDC) | Max single transfer |
| --------- | ---------------- | -------------- | ------------------- |
| Ethereum  | native USDC      | 4.00           | 1,000,000           |
| Base      | native USDC      | 0.10           | 1,000,000           |
| Polygon   | native USDC      | 0.05           | 500,000             |
| Arbitrum  | native USDC      | 0.20           | 1,000,000           |
| Solana    | native USDC      | 0.01           | 500,000             |

Bridged or wrapped USDC representations (e.g. USDC.e on Avalanche
prior to the native deployment) are not supported and must be
rejected.

## Hard limits

These limits override all other policy and may not be relaxed by
runtime override:

- **Reject limit:** Any single transfer above 1,000,000 USDC is
  rejected outright. This is independent of compliance status,
  chain-risk score, or sender verification level.
- **Hold limit:** Any single transfer between 250,000 and 1,000,000
  USDC must be placed on manual hold for treasury and compliance
  review before settlement. The reviewer's decision is recorded in
  the `override_reason` state field on resume.
- **Travel-Rule limit:** Any single transfer of 3,000 USDC or more
  requires the `step_up_verification` node before settlement
  (mirrors document 01).
- **Daily aggregate:** A single sender exceeding 5,000,000 USDC in
  outbound transfers in any rolling 24-hour window must be held for
  velocity review at the next attempt.

## Refund handling

A `refund` payment_type returns funds to a previously validated
originating address. Refunds follow the same sanctions-screening,
chain-risk, and Travel-Rule obligations as outbound transfers, but
the `step_up_verification` node is bypassed if the originating
address has been step-up-verified within the prior 30 days.

## Auto-settlement criteria

A transfer may take the `settle` path through `route_decision`
without manual review if and only if all of the following are true:

1. amount is strictly less than 3,000 USDC (below Travel Rule);
2. sanctions screening returned `clear`;
3. chain-risk analytics returned `ok` (no mixer or sanctioned-cluster
   exposure within two hops);
4. recipient address validated on a supported chain;
5. sender balance is sufficient and within the daily aggregate.

Failure of any criterion routes the transfer to `step_up_verification`,
`hold_for_review`, or `reject_payment` as appropriate.

## Override and resume protocol

When a transfer is held (`hold_for_review`) or routed to
`step_up_verification`, the case is checkpointed under its
`thread_id`. A compliance reviewer may resume the case with
`resume_from(thread_id, override_state={"compliance_status": "clear",
"override_reason": "ticket #N"})` after completing their review. The
override and reason are persisted in the audit trail.
