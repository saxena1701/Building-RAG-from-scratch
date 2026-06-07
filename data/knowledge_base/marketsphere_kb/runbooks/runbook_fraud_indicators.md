# Fraud Indicators in Orders and Accounts

*Last updated: 2024-09-15*

## Order-Level Red Flags

- Order value significantly higher than typical for the account
- Shipping address different from billing, and recently added
- Multiple cards used in rapid succession
- High-value items in categories the customer has never purchased
- Expedited shipping on first-ever order from new account
- Email address with disposable-mail domain patterns

## Account-Level Red Flags

- New account, immediate high-value order
- Multiple accounts from same IP or device
- Frequent shipping address changes
- High return rate, especially of high-resale items (electronics, luxury)
- Login attempts from unusual geographic locations

## Response Protocol

**Low confidence**: Allow order, flag account for review.

**Medium confidence**: Hold order, request additional verification (call card on file, document upload).

**High confidence**: Cancel order, refund pending auth, refer to fraud team, possibly close account.

## Important

- Do not accuse customers of fraud directly.
- Use neutral language: "I need to verify a few details before we can release this order."
- Document everything in the fraud notes section.
- Escalate to fraud@marketsphere.example for anything ambiguous.

