# Promo Code Disputes

*Last updated: 2024-09-15*

## Scenarios

- Customer claims they entered a valid code but it didn't apply.
- Customer received an email with a code but the code is rejected at checkout.
- Customer forgot to apply a code and wants the discount retroactively.

## Investigation

1. Check the code's validity (expiration, usage limits, eligibility rules).
2. Check whether the customer's cart met the requirements (minimum spend, eligible products).
3. Check whether the customer or household has used the code before.

## If Code Should Have Applied

- Apply the discount retroactively as a partial refund.
- Investigate the system issue (file engineering ticket if reproducible).

## If Code Did Not Apply Due to Customer Error

- Eligibility miss: explain the rules. Sometimes apply as goodwill for first occurrence.
- Forgot to apply: usually apply retroactively if within 7 days and code was still valid.
- Already used: explain one-use policy; do not duplicate.

## Pattern Watching

Multiple promo disputes from the same account in a short time can indicate either confusion or attempted abuse. Note pattern in account.

