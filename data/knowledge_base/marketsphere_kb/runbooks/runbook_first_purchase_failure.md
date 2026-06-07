# First Purchase Failures

*Last updated: 2024-09-15*

## Scenario

Customer's first attempted purchase fails. Common causes:
- Card declined by issuer
- Address verification mismatch
- Risk scoring flag
- Inventory shortfall during checkout

## Walking Through Card Declines

1. Confirm details are entered correctly (especially CVV, expiration, zip).
2. Suggest customer contact card issuer if details are confirmed.
3. Offer alternative payment methods.

## AVS Mismatch

If the billing address doesn't match the card's records:
- Confirm billing zip code with customer.
- Some apartment addresses cause issues with house-number-only matching.
- Suggest re-entering exact billing zip.

## Risk Flag

If our fraud system declined the order:
- We typically do not tell customer it was a risk decline (to avoid revealing controls).
- Suggest they contact us by phone for manual verification.
- For Tier 2+ agents: review the risk reasons and decide whether to manually approve.

## After Resolution

Send a welcome email and small first-purchase coupon (template W-101) to customers whose first purchase had a hiccup. Reduces churn from frustrating first experiences.

