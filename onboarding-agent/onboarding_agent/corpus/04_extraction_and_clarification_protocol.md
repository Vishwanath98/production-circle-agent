# Application extraction and clarification protocol

This document is the internal operating protocol for the
`extract_and_validate` and `request_clarification` nodes. It governs
how the agent reads a free-text signup message, which fields it must
extract, and when it is permitted to ask the applicant for a
follow-up.

## Required structured fields

Every onboarding application must be reduced to the following
structured fields before `triage_business` may run. If any required
field is missing or below the minimum-quality bar, the agent must
route to `request_clarification` instead of proceeding.

| Field             | Type      | Required | Minimum quality bar                                      |
| ----------------- | --------- | -------- | -------------------------------------------------------- |
| business_name     | string    | yes      | not empty; not a generic placeholder ("Acme", "Test")    |
| business_type     | string    | yes      | one of LLC, Corp, Sole Proprietor, NonProfit, GovEntity  |
| email             | string    | yes      | RFC-5322 valid; matches `[a-z0-9._%+-]+@[domain]`        |
| phone             | string    | yes      | E.164 format (+CCAAAAAAAAAA)                              |
| use_case          | string    | yes      | mappable to one of the A2P 10DLC categories              |
| monthly_volume    | integer   | yes      | non-negative; "stuff" / "lots" not accepted              |

A field that is present but below the quality bar (e.g.
`use_case = "stuff"`) is treated as missing for the purpose of the
clarification loop.

## Clarification loop

The clarification loop is bounded by `MAX_CLARIFY_ATTEMPTS = 2`. Each
attempt:

1. Identifies the minimum set of fields still missing or
   below-bar.
2. Composes a single follow-up message that asks for those fields
   together (never one at a time across multiple attempts).
3. Increments `clarify_attempts` in the state.
4. Loops back to `extract_and_validate` to re-read the applicant's
   reply.

If after two attempts any required field is still missing, the agent
must route to `enhanced_due_diligence` with `decision_reason =
"clarification attempts exhausted"` rather than rejecting outright —
the applicant may have a legitimate signup that the LLM extractor
struggled with.

## Use-case mapping

Common free-text descriptions map to A2P 10DLC categories as follows:

- "appointment reminders", "medication alerts", "patient
  follow-up" → **Account notifications** (sub-vertical:
  healthcare); LLC + HIPAA attestation required.
- "delivery notifications", "shipping alerts", "driver
  dispatch" → **Delivery notifications**; high-volume
  logistics may exceed Scale plan and require Enhanced.
- "two-factor authentication", "login codes", "verification
  codes" → **2FA**; lowest-friction approval path.
- "marketing", "promos", "sales notifications" → **Marketing**;
  permitted only with explicit opted-in audience attestation.
- "support", "help desk", "customer service" → **Customer care**;
  inbound-led conversations only.

A use_case the LLM cannot map to any permitted category, but that
does not match a prohibited category either, must be routed to
`standard_review` with `decision_reason = "unrecognized use case"`.

## Anti-abuse protections

- An applicant submitting more than three onboarding attempts in 24
  hours across different brand names (same email, phone, or
  beneficial owner) must be rejected with reason
  `"velocity:multi-brand"`.
- An applicant whose declared business_name matches an existing
  registered brand without a matching EIN must be routed to
  `enhanced_due_diligence`.
- An applicant whose phone number is on the platform's previously
  banned-numbers list must be rejected without a clarification loop.
