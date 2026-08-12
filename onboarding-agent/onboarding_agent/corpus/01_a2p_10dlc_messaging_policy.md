# A2P 10DLC messaging policy — Twilio-style operator framework

This document summarizes the U.S. Application-to-Person (A2P) 10-Digit
Long Code (10DLC) ecosystem operated by The Campaign Registry (TCR) on
behalf of the major U.S. mobile network operators (AT&T, T-Mobile,
Verizon, U.S. Cellular). It is the framework that governs business
messaging onboarding for this agent and its `route_by_eligibility` node.

## Background

Prior to A2P 10DLC, businesses sending messages from long-code numbers
operated in an unsanctioned grey area: messages were filtered
inconsistently, throughput was unpredictable, and there was no
registry-level accountability for spam. The 10DLC framework, which
became fully operational in 2021, requires every business sending
application-to-person messages from a U.S. long code to register both
the brand (the business) and one or more campaigns (the use case) with
TCR before traffic is permitted.

## Brand registration

Every applicant onboarded by this agent must establish a registered
brand before any campaign can be created. Brand registration requires:

- legal business name as registered with the relevant secretary of
  state;
- EIN or equivalent tax identifier;
- business street address (no PO boxes);
- registered website URL with the brand's mark or trade name visible;
- contact email at the registered domain (no free webmail providers
  for standard tier and above);
- expected monthly message volume;
- business vertical (healthcare, retail, education, public sector,
  etc.).

Brands are scored by TCR's vetting partners and assigned a trust score
between 0 and 100. The trust score determines daily message throughput
and the campaigns the brand may register.

## Campaign use-case categories

A campaign is the actual messaging program the brand wishes to operate.
Each campaign declares one of the following permitted use cases:

- **Account notifications** — order updates, shipping confirmations,
  appointment reminders;
- **Customer care** — two-way support conversations initiated by the
  customer;
- **Delivery notifications** — pickup and drop-off alerts;
- **Higher education** — university and admissions communications;
- **Polling and voting** — non-political polls only;
- **Public service announcement** — government and non-profit
  advisories;
- **Security and fraud alerts** — verification codes, login alerts,
  fraud notifications;
- **2FA** — one-time password delivery;
- **Marketing** — promotional traffic to opted-in recipients;
- **Mixed** — combination of the above with no single dominant
  category.

## Disallowed traffic

The following categories may not be registered as A2P 10DLC campaigns
and any onboarding application disclosing them as a use case must be
rejected by `route_by_eligibility`:

- **SHAFT-C content:** Sex, Hate, Alcohol (state-restricted),
  Firearms, Tobacco/Cannabis — collectively the SHAFT-C prohibition.
- **Gambling and sports betting** outside of state-licensed
  programs with verifiable licensing documentation.
- **Cannabis** including CBD-with-detectable-THC, hemp, and any
  related cannabinoid product, regardless of state legality.
- **Cryptocurrency** sales, trading, or solicitation of investment.
- **Loan and debt collection** offers from non-licensed entities.
- **Political campaigning** including partisan polling, fundraising,
  and election-day GOTV traffic.
- **High-risk financial services** including non-regulated lenders
  and any "get rich quick" pitch.
- **Phishing-adjacent traffic** including any campaign that
  impersonates a brand, agency, or service.

A use_case field containing any of the strings `spam`, `adult`,
`gambling`, `cryptocurrency`, or `political` must be rejected at the
`route_by_eligibility` node without further review.
