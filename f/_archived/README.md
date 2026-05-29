# Archived Modules

Modules moved here are no longer active in the production flow but preserved for reference.

## `telegram_normalize/`

**Archived:** 2026-05-13
**Reason:** Logic inlined into `f/flows/telegram_webhook__flow/telegram_webhook_trigger.py` (lines 76-84).
The standalone module performed `text.strip()` + event classification, which the trigger now does inline.
**Preserved for:** Reference if standalone normalization is needed outside the webhook flow.
