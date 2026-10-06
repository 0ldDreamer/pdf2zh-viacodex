# Changelog

## 0.1.0 — 2026-10-06

Initial portable Windows source project with official ChatGPT/Codex login, live model catalog, per-model reasoning choices, batched cached translation, optional margin-line cleanup, Chinese/bilingual outputs, stop/resume UI, reproducible dependency setup, tests and source packaging.

GUI login now uses the same Windows login script as the standalone launcher, preserving existing ChatGPT sessions and credentials.

Fixed Windows cmd path quoting for the GUI login launcher. Script output and failures now appear in the GUI log; real shell checks cover Chinese paths, spaces and exit codes.

Chinese and bilingual PDF filenames now include the model ID from the pinned translation job profile.

Login always starts a fresh isolated browser authorization. Only successful, checked credentials activate the new account, with the prior login preserved in private local account history; cancellation/failure leaves the current account unchanged.

Isolated login homes now live in private application state outside TEMP, avoiding the official CLI warning about creating PATH helper binaries in temporary storage.

Pending login exposes a Cancel login button and expires after five minutes. Cancel/timeout stops the login process, cleans the isolated login home, preserves the existing account and restores controls. Model refresh and translation remain disabled while login is pending.

GUI layout tests now explicitly set allowable window sizes instead of inheriting cloud desktop limits, and cover expanded logs on the 751px cloud-sized desktop.

Keep only the four Chinese-named CMD launchers; each directly invokes its installer, GUI or command runner. Documentation, packaging and Windows launcher checks use the same entrypoints.
