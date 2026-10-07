# 开发说明

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

自动测试不需要账号、不发起官方模型推理；模型接口和批量执行使用明确的模拟结果。覆盖 PDF 左右配对、非连续页码、源完整性、行号副本处理、账号模式限制、官方模型枚举适配、占位符、缓存去重、失败交付阻断及 GUI 停止继续。GUI 测试需要桌面/Tk；无桌面环境跳过。

真实登录、模型查询、首次模型资产下载和实际翻译需另做集成验证。CI 不配置任何开发者凭据。

## 修改边界

保持官方 ChatGPT 登录、清除 API Key 环境变量。避免吞掉模型错误并把原文作为译文返回。改动依赖版本必须重新验证三个适配点、Windows 子进程、代表页渲染与 .runtime 路径隔离。不得把真实论文和 auth.json 加入测试夹具。
