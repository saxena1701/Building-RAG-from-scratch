# Resolving Duplicate Charges

*Last updated: 2024-09-15*

## Most Common Causes

1. **Authorization + charge confusion**: Customer sees a pending authorization AND the final charge. The auth typically drops off in 3-5 business days. This is not actually a duplicate charge.
2. **Failed checkout retry**: Customer hit "Place Order" twice during slow loading; system normally prevents this but rare cases slip through.
3. **Subscription auto-renewal not anticipated by customer**.
4. **Genuine system error**: actual duplicate charge.

## Investigation Steps

1. Look up customer in CRM, find orders within last 14 days.
2. Check for duplicate orders with similar timestamps (within 10 minutes).
3. Check the payment authorization log; pending auths show separately from completed charges.
4. If subscription, identify which subscription generated the charge and notify customer.

## Resolution

**If pending auth only (not duplicate charge)**:
- Explain the difference between authorization and charge.
- Provide expected drop-off date.
- No action needed; auth releases automatically.

**If genuine duplicate**:
- Refund the duplicate immediately.
- Issue $10 store credit as goodwill gesture.
- File internal incident ticket (template DUP-001) for engineering to review root cause.

**If subscription**:
- Show customer their subscription schedule.
- Offer to cancel if they didn't realize they had one.
- Refund the most recent charge as goodwill if within 7 days and customer can demonstrate no use.

