# Contributing

Use Python 3.11/3.12 and the pinned requirements. Run `project.py bootstrap` and `project.py test` before submitting a change. Tests do not require personal accounts or secrets.

Keep runtime credentials, documents, generated PDFs, logs and caches out of commits. Changes to dependencies or model protocols need integration checks using an account you control; describe tested versions and limits in the PR. Check original PDF hashes, placeholder/citation fidelity and representative rendered pages when changing layout or translation.

Public issues should contain a sanitized error summary, software versions and a synthetic reproducer. Do not attach auth.json, full diagnostic folders or private papers. Contributions use AGPL-3.0-or-later.
