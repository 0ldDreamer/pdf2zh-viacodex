# Third-party components

The application integrates pdf2zh-next 2.8.2 and BabelDOC 0.5.24, both distributed under AGPL-3.0. This project is distributed under AGPL-3.0-or-later; see [LICENSE](../LICENSE). Dependency sources, changes and licenses remain available at their upstream projects:

- pdf2zh-next: https://github.com/PDFMathTranslate-next/PDFMathTranslate-next
- BabelDOC: https://github.com/funstory-ai/BabelDOC
- PyMuPDF: https://github.com/pymupdf/PyMuPDF (AGPL / commercial licensing)
- Codex CLI: https://github.com/openai/codex (Apache-2.0)

Dependencies are installed separately, not bundled in the source release. The bootstrap changes three cache/config path assignments in the dedicated virtual environment; the reproducible modifications are in app/vendor_isolation.py. Translation batching is installed by runtime adapters in app/batch_translate.py. All other dependency license obligations still apply.

This is an independent community project, not an official OpenAI product. ChatGPT subscription access and model availability remain controlled by OpenAI.
