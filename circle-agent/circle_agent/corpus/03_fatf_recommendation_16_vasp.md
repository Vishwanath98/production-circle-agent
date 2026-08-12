# FATF Recommendation 16 — Virtual Asset Service Provider obligations

This document summarizes the Financial Action Task Force (FATF)
Recommendation 16 as updated by the October 2021 Updated Guidance on a
Risk-Based Approach to Virtual Assets and Virtual Asset Service
Providers (VASPs), to the extent it governs USDC transfers handled by
this agent.

## Scope

Recommendation 16 extends the "Travel Rule" to VASPs and to transfers
of virtual assets between VASPs. It is the international counterpart to
the FinCEN Travel Rule covered in document 01, but with a lower
threshold (USD/EUR 1,000) recommended for most jurisdictions and a
broader definition of covered transfers.

Recommendation 16 covers any transfer of virtual assets between two
VASPs, or between a VASP and a non-custodial ("unhosted") wallet, where
the originator and beneficiary are different natural or legal persons.

## Required transmittal information

For every covered transfer the originating VASP must obtain and
transmit, and the beneficiary VASP must collect and retain, the
following:

- the originator's full name;
- the originator's account identifier (e.g. wallet address, customer
  reference);
- the originator's physical address, or alternatively the originator's
  national identity number, customer identification number, or date and
  place of birth;
- the beneficiary's full name; and
- the beneficiary's account identifier (e.g. wallet address).

The information must travel "immediately and securely" with the
transfer. Beneficiary VASPs that receive a covered transfer without the
required information must take risk-based action — return the funds,
freeze the transfer, or report the originating VASP — as set out in
their national regulator's interpretation of Recommendation 16(b).

## Risk-based requirements for unhosted-wallet counterparties

Recommendation 16 paragraph 196 directs VASPs to apply enhanced due
diligence to transfers where the counterparty is an unhosted (self-
custodial) wallet. Enhanced due diligence may include:

- additional originator verification beyond the customer-identification
  data already on file;
- on-chain analytics on the unhosted address (mixer exposure, cluster
  size, prior sanctioned-address contact);
- a senior-compliance-officer attestation for transfers above a
  jurisdiction-specific threshold; and
- in some jurisdictions, refusal to settle absent counterparty
  verification.

## High-risk wallet typologies

Wallets exhibiting any of the following on-chain typologies must be
held for enhanced due diligence regardless of nominal transfer amount:

- exposure to mixers (Tornado Cash, Wasabi, Samourai, ChipMixer);
- exposure to darknet markets within two hops;
- prior receipt from a sanctioned address;
- exposure to a known ransomware payout cluster; and
- behavior consistent with a peel chain or rapid layering pattern.

## Sunrise problem

Many jurisdictions have not fully implemented Recommendation 16 in
local law, creating a "sunrise" period during which a U.S.-regulated
VASP may be required to transmit Travel Rule data to a counterparty
VASP that is not required to receive it. The conservative posture
adopted by this agent is to transmit the required data on every
covered transfer regardless of counterparty jurisdiction.
