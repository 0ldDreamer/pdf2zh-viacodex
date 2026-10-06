# 发布到 GitHub

源代码已与本机运行数据分离。只上传 Git 跟踪的源码，或者上传 `scripts/package_release.py` 生成的源码 ZIP。

```powershell
git init
git add .
git status --short
# 确认没有 .runtime、.venv、outputs、auth.json 或自己的 PDF。
git commit -m "Initial release of pdf2zh-viacodex"
# 在 GitHub 创建自己的空仓库后：
git branch -M main
git remote add origin https://github.com/YOUR_ACCOUNT/pdf2zh-viacodex.git
git push -u origin main
```

`YOUR_ACCOUNT` 只存在于本说明示例，不是项目依赖。无需提交 Node/Python 安装目录；另一台电脑运行 安装依赖.cmd 重建。

生成可分享源码包：

```powershell
.\.venv\Scripts\python.exe -B scripts/package_release.py
```

脚本采用源码白名单打包并检查文件名和疑似凭据；源码包位于 `outputs/releases/`。不要将整个已登录的目录直接压缩。账号凭据即使被 .gitignore 忽略，也仍是本机敏感文件。

仓库提供 GitHub Actions 的 Windows / Python 3.11、3.12 检查，不需要 secrets。发布前检查 README 中的验证范围；真实跨电脑测试完成后再扩大平台支持声明。
