# Plan tiers, throughput, and KYB track mapping

This document is the internal operating policy that maps an applicant's
declared monthly message volume to a plan tier, a default KYB track,
and a 10DLC trust-score expectation. It binds the `select_plan_tier`
node and the `triage_business` node.

## Plan-tier table

| Monthly volume        | Plan tier  | Default KYB track | Default trust score expected |
| --------------------- | ---------- | ----------------- | ---------------------------- |
| 0 – 1,000             | Free       | Light             | n/a (low trust acceptable)   |
| 1,001 – 50,000        | Starter    | Light → Standard  | ≥ 40                         |
| 50,001 – 500,000      | Growth     | Standard          | ≥ 60                         |
| 500,001 – 2,000,000   | Scale      | Standard → Enhanced | ≥ 75                       |
| 2,000,001 – 5,000,000 | Enterprise | Enhanced          | ≥ 80                         |
| > 5,000,000           | Enterprise | Enhanced (manual review required) | ≥ 90        |

## Track-switching rules

The default KYB track derived from the volume table is overridden upward
(not downward) by any of the following:

1. **Business type**: sole proprietors are eligible for the Light track
   only up to the Starter plan; LLCs and corporations default to
   Standard and may move up to Enhanced.
2. **Vertical**: any applicant in a FinCEN high-risk vertical (see
   corpus document 02) is routed to Enhanced regardless of volume.
3. **Domain mismatch**: a registered-domain mismatch with the legal
   business name promotes to Enhanced.
4. **Velocity**: an applicant that submits more than three onboarding
   attempts in a 24-hour window across different brand names is
   promoted to Enhanced and flagged for fraud review.

## Throughput limits by trust score

A2P 10DLC throughput is set by the brand's trust score and the
campaign's use-case category. The aggregate throughput across all
campaigns under a single brand is governed by the operator's daily
message cap, which the platform must respect to avoid carrier-level
blacklisting.

| Trust score band | T-Mobile daily cap | AT&T daily cap | Verizon daily cap |
| ---------------- | ------------------ | -------------- | ----------------- |
| 0 – 24           | 2,000              | 1,000          | 1,000             |
| 25 – 49          | 10,000             | 5,000          | 5,000             |
| 50 – 74          | 100,000            | 50,000         | 50,000            |
| 75 – 100         | 200,000            | 100,000        | 100,000           |

An applicant whose declared monthly volume implies a daily send rate
above the band's combined cap (i.e. monthly / 30 > sum of caps) must be
held for `enhanced_due_diligence` until the brand achieves a sufficient
trust score.

## Auto-approve criteria

An applicant may take the `auto_approve` path through
`route_by_eligibility` if and only if:

1. monthly volume ≤ 50,000;
2. business type is LLC, Corp, or Sole Proprietor;
3. business email is on the registered company domain (no free
   webmail);
4. use case is a permitted A2P 10DLC category (see corpus document 01);
5. verification score returned by `verify_identity` is ≥ 0.75; and
6. no sanctions or registry red flag was raised.

Failure of any criterion routes the applicant to `fast_track` (if the
verification score is between 0.6 and 0.75) or `standard_review` (if
the verification score is between 0.4 and 0.6) before provisioning.
