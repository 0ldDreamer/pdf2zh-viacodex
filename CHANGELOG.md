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

Python discovery now tolerates missing launcher versions on Windows PowerShell 5.1, falls back to other supported runtimes, and reports a clear installation hint if none is available. Real shell regression checks cover missing 3.12, PATH fallback and explicit invalid runtimes.

Apply the selected light card interface: teal accents, grouped file/settings sections, header login controls and a resizable log panel. Existing translation, model discovery and login/resume behavior are preserved.

Align the light UI with its preview: show the locally stored ChatGPT login status, draw checkmark indicators instead of platform crosses, and restore borders on secondary buttons. Cancelled authorization retains the original account badge.

The header login button shows Switch account when a ChatGPT session is saved, Sign in when signed out, and Cancel login during authorization.

Localize common Codex browser-login messages in the GUI log and the shared login launcher failure hint. Authorization URLs, device-login commands and unknown diagnostics are preserved.

Theme model and reasoning dropdowns with matching fonts, comfortable row spacing, light teal selection and consistent borders/hover colors.

Progress logs show paragraph counting in progress while totals are unavailable instead of 0/0, and suppress duplicate preparation notices. Counted paragraph progress and cache/batch statistics remain visible afterwards.
