# 开发与贡献

## 目录

- `app/runtime.py`：项目路径、环境隔离、CLI 发现与 ChatGPT 模式检查；翻译专用 `pdf-https` provider 沿用官方认证，关闭 WebSocket。登录和模型目录查询仍使用内置 `openai`。
- `app/model_assets.py`：预下载并复用解析模型，按依赖的 SHA3-256 校验；下载源失败时切换，完整校验后原子替换缓存。
- `app/model_catalog.py`：官方 app-server JSON-RPC 握手、模型分页、目录刷新与缓存。
- `app/pdf_gui.py`：Tk 界面、后台工作、停止/继续、登录与模型选择。
- `app/translate_pdf.py`：只读复制输入、行号清理、原生解析排版、交付验证与对照组合。
- `app/translation_instructions.md`：翻译调用专用指令，替换通用编程指令；仅翻译子进程关闭应用、插件和 shell 工具。
- `app/translation_settings.py`：共享调度参数；每批最多 12 段、最多 8 批并行，128 个段落线程为批次提供输入。
- `app/batch_translate.py`：按段落 ID 返回 JSON，批量并行、占位符校验、缓存、进度和失败标记。
- `app/vendor_isolation.py`：对专用虚拟环境三个缓存/配置路径进行可重复适配；不修改系统 Python。
- `.runtime/`：所有运行状态，包括账号、模型、字体、临时 PDF、日志和缓存，禁止提交。

默认运行状态在项目 `.runtime`；高级使用可设置 `PDF2ZH_VIACODEX_STATE_DIR` 到其他可写目录。移动项目后请重建 `.venv`，Python 虚拟环境不能视为可移植成品。

## 测试

```powershell
.\.venv\Scripts\python.exe -B project.py bootstrap
.\.venv\Scripts\python.exe -B project.py test
```

自动测试不需要账号、不发起官方模型推理；模型接口和批量执行使用模拟结果。覆盖 PDF 页面配对与源完整性、行号副本处理、模型与强度、占位符与缓存、失败交付阻断、GUI 停止/继续、账号切换与取消/超时、Windows 启动脚本和模型下载校验。GUI 测试需要桌面/Tk；无桌面环境跳过。

真实登录、模型查询、首次模型资产下载和实际翻译需另做集成验证。CI 不配置任何开发者凭据。

## 验证范围

v1.0 发布时，本机 Windows 的 35 项自动测试及 GitHub Actions 的 Windows / Python 3.11、3.12 检查均通过。本机也完成了真实 ChatGPT 登录、官方模型查询、PDF 解析排版和翻译验证，抽查了中文、公式、数值、引用及对照页布局。

尚未在第二台物理电脑上验证；测试结果不代表所有账号、网络和论文版式均可正常工作。

## 贡献要求

使用 Python 3.11 或 3.12 和项目固定版本依赖。提交修改前运行上述初始化和测试命令，在 PR 中说明改动、验证方式及限制。

涉及依赖或模型协议的修改，需使用自己的账号做集成验证。涉及排版或翻译的修改，应检查原 PDF 哈希、占位符、公式与引用，并渲染代表页检查布局。

提交 Issue 时提供软件版本、脱敏错误日志及可复现的合成样例。不要提交账号凭据、真实论文、生成的 PDF、运行日志或缓存。贡献代码采用 AGPL-3.0-or-later。

## 修改边界

保持官方 ChatGPT 登录、清除 API Key 环境变量。避免吞掉模型错误并把原文作为译文返回。改动依赖版本必须重新验证三个适配点、Windows 子进程、代表页渲染与 .runtime 路径隔离。不得把真实论文和 auth.json 加入测试夹具。

## 源码打包

```powershell
.\.venv\Scripts\python.exe -B scripts/package_release.py
```

源码包生成在 `outputs/releases/`，脚本按白名单收集源码并检查疑似凭据。不要直接压缩已登录的整个项目目录；`.runtime/`、`.venv/` 和论文数据不应随源码分享。
