# pdf2zh-viacodex

面向 Windows 的英文论文 PDF 翻译工具：**pdf2zh-next 负责解析和排版，官方 Codex CLI 负责翻译**。使用自己的 ChatGPT 账号登录，无需配置 API Key；可用模型和额度取决于账号权限与套餐。

![图形界面](docs/images/main-window.png)

截图中的文件与保存路径仅作示例。

## 功能

- 英文 PDF 翻译为简体中文，保留公式、图片和版式。
- 生成纯中文、中英对照或两种版本；对照版中文在左、原文在右。
- 翻译全文或指定页码，可选清理论文边栏行号。
- 在界面选择模型和思考强度，模型列表从官方获取。
- 支持停止、继续及译文缓存复用，可查看运行日志。
- 自选保存位置，译文文件名包含本次使用的模型名称和思考强度。

## 运行要求

- Windows 10/11。
- Python **3.11 或 3.12**，包含 Tcl/Tk。
- 具有 Codex 使用权限的 ChatGPT 账号，以及可访问依赖下载站点和 OpenAI 的网络。
- 已安装官方 Codex CLI 或 Codex 桌面应用；否则需先安装 Node.js LTS，安装脚本会下载官方 CLI。

## 快速开始

1. 下载或克隆源码，解压到可写的目录。
2. 双击 **`安装依赖.cmd`** 安装依赖。
3. 双击 **`登录ChatGPT.cmd`**，在浏览器完成授权。
4. 双击 **`翻译PDF.cmd`**，选择 PDF、保存位置及翻译选项。
5. 选择模型与思考强度，点击 **开始翻译**。

安装时会预下载并校验 PDF 解析模型，后续翻译复用本地缓存。首次安装及字体准备可能较慢。遇到问题可运行 **`检查环境.cmd`**。

默认译文保存在 `outputs/`。原始 PDF 保持不变，账号、缓存和运行文件保存在本机 `.runtime/`，Python 依赖位于 `.venv/`。论文文本会发送给 OpenAI 的 Codex 服务。

复杂表格、扫描件和行号的处理效果取决于原文版式；完成后建议检查译文中的公式、数值和引用。

## 文档

- [使用说明与故障排查](docs/usage.md)
- [开发与贡献](docs/development.md)
- [更新记录](docs/CHANGELOG.md)

## 开源与致谢

采用 **AGPL-3.0-or-later**，依赖许可见 [第三方依赖与许可](docs/THIRD_PARTY_NOTICES.md)。感谢 [pdf2zh-next](https://github.com/PDFMathTranslate/PDFMathTranslate-next)、BabelDOC、PyMuPDF 和 [Codex CLI](https://github.com/openai/codex)。本项目不是 OpenAI 官方产品。
