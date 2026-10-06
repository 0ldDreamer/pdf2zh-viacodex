# Changelog

## 0.1.0 — 2026-10-06

Initial portable Windows source project with official ChatGPT/Codex login, live model catalog, per-model reasoning choices, batched cached translation, optional margin-line cleanup, Chinese/bilingual outputs, stop/resume UI, reproducible dependency setup, tests and source packaging.

GUI login now uses the same Windows login script as the standalone launcher, preserving existing ChatGPT sessions and credentials.

Fixed Windows cmd path quoting for the GUI login launcher. Script output and failures now appear in the GUI log; real shell checks cover Chinese paths, spaces and exit codes.

Chinese and bilingual PDF filenames now include the model ID from the pinned translation job profile.

Login always starts a fresh isolated browser authorization. Only successful, checked credentials activate the new account, with the prior login preserved in private local account history; cancellation/failure leaves the current account unchanged.
