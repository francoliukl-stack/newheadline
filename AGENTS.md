# Project Agent Instructions

## Headlines AI Review

- Before running or modifying `scripts/ai_review_suggest.py`, read `docs/ai_review_labeling_rules.md`.
- The rulebook is both human-readable and machine-readable; keep the JSON block valid.
- When human review overrides AI Status, run `scripts/ai_review_suggest.py` once to write feedback fields, then update the rulebook only for repeated or high-value patterns.
- Every rulebook update must add a dated entry under `Change Log`.
- Hard gates remain stronger than the rulebook: explicit duplicate, missing Source URL and missing Publish Date must not be auto-accepted.
