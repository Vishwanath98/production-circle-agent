# OFAC sanctions screening — operating procedure

This document describes the sanctions-screening obligations imposed on
USDC transfers by the U.S. Office of Foreign Assets Control (OFAC) and
the operational procedure this agent must follow before any
`settle_payment` action.

## Legal basis

Treasury / OFAC regulations (31 CFR Chapter V) prohibit U.S. persons,
including U.S.-incorporated stablecoin issuers and their customers,
from engaging in transactions with persons, entities, or jurisdictions
listed on the Specially Designated Nationals and Blocked Persons (SDN)
list, the Sectoral Sanctions Identifications (SSI) list, or any
comprehensive sanctions program (Cuba, Iran, North Korea, Syria, Crimea
region, occupied territories of Ukraine).

OFAC's October 2018 guidance on virtual currency expressly extended
these prohibitions to wallet addresses and other on-chain identifiers
when published in association with a designated person. As of the date
of writing, more than 250 individual wallet addresses across Ethereum,
Bitcoin, Tron, and other chains have been added to the SDN list.

## Screening requirements

Every USDC transfer initiated through this agent must, prior to
settlement, be screened against:

1. The originator account and customer record (name, date of birth,
   country of residence, beneficial-owner KYB data).
2. The beneficiary wallet address (lower-cased, normalized to the
   chain's canonical format).
3. The beneficiary's identified counterparty if known (custodian,
   exchange, VASP).
4. Any free-text memo or invoice reference attached to the transfer.

Screening must use both exact-match address lookups and fuzzy-match
name matching with a similarity threshold tuned to current OFAC
guidance. Address matches are dispositive: a single hit against the
SDN list requires immediate rejection and blocking.

## Decision matrix

- **Sanctioned hit on the beneficiary address:** the transfer must be
  rejected and the funds blocked. A blocking report must be filed with
  OFAC within 10 business days.
- **Sanctioned hit on a related counterparty (custodian, exchange):**
  the transfer must be held for compliance review and not settled until
  the relationship is documented as a non-blocked path.
- **Match on a comprehensively sanctioned jurisdiction:** the transfer
  must be rejected regardless of amount or counterparty.
- **No hit:** proceed to the chain-risk analytics step. A clean
  sanctions result alone does not authorize settlement.

## Test addresses

For development and end-to-end testing this agent treats the address
`0x5555555555555555555555555555555555555555` (40 hex `5`s) as a
deterministically sanctioned beneficiary. Any production transfer to
this address must be rejected by `screen_compliance` with the
`sanctioned` route label.

## Reporting

Every block, rejection, and held-for-review event must be appended to
the compliance audit trail (`path_log` + structured event log) and made
available through the agent's checkpoint thread for compliance review.
