# Customer Identity Verification

*Last updated: 2024-09-15*

## When Verification is Required

- Account access requests where the contact can't immediately authenticate
- High-value order changes (> $1000)
- Refund issuance to a payment method other than the original
- Adding new shipping addresses to accounts with order history
- Subscription cancellations involving auto-renewal disputes

## Verification Levels

**Level 1 (basic)**: Confirm account email and one of:
- Recent order number
- Phone number on file
- Billing address

**Level 2 (elevated)**: Required for high-value or sensitive changes:
- Email confirmation link AND
- One of: last 4 of card on file, full billing address, security question

**Level 3 (highest)**: Required for password reset on accounts with red flags:
- Email + phone verification (both)
- Photo ID upload (in extreme cases of suspected account takeover)

## If Verification Fails

- Do not provide account information or make changes.
- Suggest customer log in directly (cuts out verification).
- Offer to send a secure account-recovery email to the address on file.
- Document attempted access in CRM (potential takeover attempt).

## Never

- Confirm specific information they didn't provide ("Yes, that's the right last 4...").
- Override verification because the customer seems frustrated.
- Process irreversible actions on partial verification.

