# FinCEN Travel Rule — 31 CFR 1010.410(f) summary

This document summarizes the U.S. FinCEN "Travel Rule" obligation as it
applies to USDC stablecoin transfers initiated through the Circle Mint or
Circle Programmable Wallets APIs. It restates the substantive obligations
contained in 31 CFR 1010.410(f) and FinCEN guidance FIN-2019-G001 in
plain language; it is not legal advice.

## Threshold

The Travel Rule applies to any funds transmittal of $3,000 USD-equivalent
or more. For USDC, the operative figure is the face-value USD-equivalent
amount at the time of transmittal. Transfers of less than $3,000 are
exempt from the originator-and-beneficiary information transmittal
requirement set out below, but remain subject to suspicious-activity
monitoring, OFAC screening, and recordkeeping obligations under 31 CFR
1010.410(e).

## Information required to travel with the payment

For each covered transfer the transmitting financial institution must
collect and forward to the next financial institution in the payment
chain the following originator information:

- the originator's full legal name;
- the originator's account number (or unique customer identifier);
- the originator's street address;
- the amount of the transmittal order;
- the execution date of the transmittal order; and
- the identity of the recipient's financial institution.

If known, the following recipient information must also travel with the
order: full legal name, address, account or unique identifier, and any
other specific identifier of the recipient.

## Step-up verification

Transmittals at or above the $3,000 threshold require step-up
verification of the originator's identity if the originator is not an
established customer of the transmitting institution. Step-up means
collecting and independently verifying government-issued identification
in addition to the customer-identification data captured at
account-opening. A transfer that cannot be step-up-verified must be held
pending verification, not settled.

## Recordkeeping

Records of each covered transmittal — including all originator and
beneficiary information collected, the transmittal order, and the
verification documents used for step-up — must be retained for five
years and made available to FinCEN or the appropriate functional
regulator upon request.

## Application to virtual-asset transfers

FIN-2019-G001 clarifies that "value that substitutes for currency"
(including convertible virtual currencies such as USDC) is covered by
the Travel Rule on the same basis as fiat funds transmittals. The
$3,000 threshold is denominated in U.S. dollars; for USDC the
denomination is treated as 1 USDC = 1 USD for purposes of threshold
determination, even when the originator and beneficiary settle on
different chains.

## Operational implications for this agent

- Any payment of 3,000 USDC or more must be routed through the
  `step_up_verification` node before the `settle_payment` node may
  execute.
- A transmittal lacking originator-side identification cannot be
  auto-settled regardless of compliance-screening status.
- Payments of less than 3,000 USDC remain subject to the full
  sanctions-screening pipeline; the Travel Rule exemption is narrowly
  limited to the information-transmittal obligation.
