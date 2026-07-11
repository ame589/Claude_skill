# Example run

Given a change to `src/payments.py` (adding a `tax_rate` parameter to
`calculate_total` and a new `apply_discount` function) in a repo where
`checkout.py`, `invoice.py`, and a test all import `calculate_total`, the skill
produces:

```
# 🧭 Blast Radius Report

**Overall risk: 🟡 MEDIUM** (score 55/100)

## ✅ Ship-readiness checklist
- [MISSING TEST] `src/payments.py` changed but no matching test in this diff.
- [MISSING TEST] Symbols with external callers changed but no tests touched.
- [REVIEW DOCS] Public symbols changed — verify docs/README are still accurate.
- [CHANGELOG] Repo has a CHANGELOG but this diff does not update it.

## 🔗 Reverse dependencies (who calls what you changed)

### `src/payments.py` — risk 40/100
Changed symbols: `apply_discount`, `calculate_total`
- `calculate_total` ← `src/checkout.py`, `src/invoice.py`, `tests/test_payments.py`
```

From here the skill would: write/adjust tests for the new `tax_rate` behavior
and `apply_discount`, check that `checkout.py` and `invoice.py` still pass a
correct call (they do — the new parameter defaults), review the docs for the
changed signature, and add a CHANGELOG entry. Then re-run to confirm the
checklist clears.
