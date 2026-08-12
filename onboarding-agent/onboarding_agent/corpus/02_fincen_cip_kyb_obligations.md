# FinCEN Customer Identification Program (CIP) — KYB application

This document summarizes the U.S. FinCEN Customer Identification
Program rule (31 CFR 1020.220) and the Customer Due Diligence (CDD)
Final Rule (FinCEN-2016-0014), to the extent they govern business
onboarding handled by this agent. CIP was originally written for
banks; the messaging platform's onboarding pipeline applies the same
underlying obligations as an industry-best-practice baseline, mapped
onto the three KYB tracks (light / standard / enhanced).

## Required identifying information

The CIP rule requires that, before a business customer is onboarded,
the following information be collected and verified:

- legal name of the legal entity;
- street address (no PO boxes; a registered agent's address is
  acceptable only if the entity's principal place of business is also
  recorded);
- date of formation, place of formation, and current good-standing
  status of the entity;
- a taxpayer identification number (EIN for U.S. entities; foreign tax
  identifier for non-U.S. entities); and
- the names, addresses, dates of birth, and government-identification
  numbers of any beneficial owner holding 25% or greater equity, plus
  one individual with significant managerial control.

## Verification methods

Verification may be performed by documentary or non-documentary means.
Documentary verification includes inspection of the entity's
certificate of formation, a recent good-standing certificate from the
state of formation, and government-issued identification for each
beneficial owner. Non-documentary verification includes querying
independent commercial registries (e.g. the relevant state's Secretary
of State portal), comparing the EIN against IRS records, and
authenticating beneficial-owner identification against credit-bureau
data.

The light KYB track may rely entirely on non-documentary verification
for small senders with low monthly volume. The standard track combines
non-documentary verification with at least one documentary check
(typically the certificate of formation or domain ownership). The
enhanced track requires both documentary and non-documentary
verification of every beneficial owner and significant manager.

## Triggers for enhanced due diligence

The agent must route an applicant to the enhanced KYB track when any
of the following are true:

- the entity's stated business vertical is on the FinCEN high-risk
  list (cash-intensive businesses, money-service businesses,
  precious-metals dealers, art and antiques dealers, third-party
  payment processors);
- the entity has a beneficial owner resident in a FATF-listed
  high-risk jurisdiction (see corpus document 03);
- the entity has been operating for less than 12 months and expects
  monthly message volume above 500,000;
- the entity declines to disclose a beneficial owner who holds at
  least 25% equity; or
- any element of the application returns a sanctions, registry, or
  domain-verification mismatch.

## Risk indicators and red flags

The following red flags require additional manual review even if the
applicant clears the verification threshold:

- a registered-agent address shared by more than 25 unrelated
  entities;
- a beneficial owner who is a politically exposed person (PEP);
- a contact email at a free webmail provider (gmail, yahoo, etc.)
  combined with monthly volume above the starter tier;
- a business name nearly identical to a well-known brand without a
  documented trademark license;
- inconsistencies between the application and the relevant
  secretary-of-state record (address, officers, formation date).

## Recordkeeping

CIP requires retention of the identifying information for at least
five years after the account is closed. For this agent, the relevant
records are the `extracted_info` snapshot, the verification scores
returned by `verify_identity`, and the final `decision`, all of which
must be persisted in the audit checkpoint thread.
