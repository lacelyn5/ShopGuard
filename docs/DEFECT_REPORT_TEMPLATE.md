# Defect report template

**ID:** BUG-___
**Title:** [Component] — short, observable failure
**Status:** New / Reproduced / Investigating / Fixed / Closed
**Severity:** Critical / High / Medium / Low
**Priority:** P1 / P2 / P3 / P4
**Environment:** baseline v5 / intentionally buggy v5; browser & OS; timestamp (UTC)
**Preconditions:** account/session, cart state, URL, product used

## Steps to reproduce
1.
2.
3.

## Expected behavior
[Explain what should occur based on the current specification.]

## Actual behavior
[What actually occurred, including status code or exact UI behavior.]

## Reproducibility
[x/y attempts; if inconsistent, note possible external server instability.]

## Evidence
- Screenshot / Playwright trace location: `reports/...`
- Relevant response body excerpt with no tokens/passwords:
- Request and response IDs when safe to share:

## Impact / analysis
[Who is affected? Is there a workaround?]

## Notes
**Do not file expected behaviors or seeded defects as discoveries without independent reproduction.** Any intentional defects in the buggy training version should be identified as such, not presented as an incident on the baseline store.
