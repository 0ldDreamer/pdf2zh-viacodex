# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check npm for a stable Codex release and install it in the project's runtime."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import uuid

from runtime import CODEX_ACTIVE, CODEX_RELEASES, ROOT, find_codex

REGISTRY = 'https://registry.npmjs.org'
STABLE_VERSION = r'[0-9]+\.[0-9]+\.[0-9]+'
HIDDEN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def version_key(version):
    base, sep, _ = version.partition('-')
    return tuple(map(int, base.split('.'))) + (not sep,)


def cli_version(executable):
    result = subprocess.run([str(executable), '--version'], capture_output=True, text=True,
                            timeout=15, creationflags=HIDDEN, cwd=ROOT)
    match = re.search(r'^codex-cli (' + STABLE_VERSION + r'(?:-[0-9A-Za-z.-]+)?)\s*$',
                      result.stdout, re.MULTILINE)
    if result.returncode or not match:
        raise RuntimeError('无法读取当前 Codex CLI 的版本。')
    return match[1]


def check_update():
    try:
        current = cli_version(find_codex())
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        current = None
    request = urllib.request.Request(REGISTRY + '/@openai%2fcodex/latest',
                                     headers={'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            release = json.load(response)
        latest = release.get('version') if release.get('name') == '@openai/codex' else None
    except (urllib.error.URLError, TimeoutError):
        # Honor the same npm registry and proxy settings as the project installer.
        command = npm_command()
        result = subprocess.run(command + [
            'view', '@openai/codex@latest', 'version', '--json', '--fetch-retries=0',
            '--fetch-timeout=12000', '--cache', str(ROOT / 'cache' / 'npm'),
        ], capture_output=True, text=True, timeout=20, creationflags=HIDDEN, cwd=ROOT)
        if result.returncode:
            raise RuntimeError('无法连接 npm 仓库，请检查网络或 npm 代理设置。')
        latest = json.loads(result.stdout)
    if not isinstance(latest, str) or not re.fullmatch(STABLE_VERSION, latest):
        raise RuntimeError('npm 仓库未返回有效的 Codex CLI 版本。')
    return current, latest


def update_available(current, latest):
    return current is None or version_key(current) < version_key(latest)


def npm_command():
    npm = shutil.which('npm.cmd')
    node = shutil.which('node.exe')
    if not npm or not node:
        raise RuntimeError('请先安装包含 npm 的 Node.js LTS，再检查并安装更新。')
    npm_cli = Path(npm).resolve().parent / 'node_modules' / 'npm' / 'bin' / 'npm-cli.js'
    if not npm_cli.is_file():
        raise RuntimeError('找不到 npm 的程序文件，请检查 Node.js 安装。')

    return [node, str(npm_cli)]


def install_update(version):
    if not re.fullmatch(STABLE_VERSION, version):
        raise ValueError('无效的 Codex CLI 版本。')
    if os.environ.get('PDF2ZH_CODEX_EXE'):
        raise RuntimeError('当前通过 PDF2ZH_CODEX_EXE 指定了 CLI，请更新该路径下的 Codex CLI。')
    command = npm_command()

    CODEX_RELEASES.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='download-', dir=CODEX_RELEASES) as staging:
        stage = Path(staging)
        try:
            result = subprocess.run(
                command + ['install', '--prefix', str(stage),
                 '--cache', str(ROOT / 'cache' / 'npm'), '--ignore-scripts', '--no-audit',
                 '--no-fund', '@openai/codex@' + version],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=240, creationflags=HIDDEN, cwd=stage,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('下载 Codex CLI 超时，请检查网络后重试。') from exc
        if result.returncode:
            raise RuntimeError(f'npm 安装失败（退出码 {result.returncode}），请检查网络和 Node.js。')
        executable = next((stage / 'node_modules').glob('@openai/codex-win32-*/vendor/*/bin/codex.exe'), None)
        if executable is None or cli_version(executable) != version:
            raise RuntimeError('新 CLI 未通过版本检查，原版本仍可使用。')

        # Publish only after verification. Existing processes can keep using their binary.
        relative_exe = executable.relative_to(stage)
        release = CODEX_RELEASES / (version + '-' + uuid.uuid4().hex[:8])
        stage.replace(release)
        temporary = release.with_suffix(release.suffix + '.active-tmp')
        try:
            temporary.write_text((release / relative_exe).relative_to(CODEX_RELEASES).as_posix(),
                                 encoding='utf-8')
            temporary.replace(CODEX_ACTIVE)
        finally:
            temporary.unlink(missing_ok=True)
