# SPDX-License-Identifier: AGPL-3.0-or-later
"""Source-checkout command entrypoint (no user-specific paths)."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
import uuid
import time

PROJECT_ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(PROJECT_ROOT/'app'))
from runtime import prepare_environment, ensure_chatgpt_auth, find_codex, CODEX_HOME, ROOT


def login_cancel_requested():
    flag=os.environ.get('PDF2ZH_LOGIN_CANCEL_FILE')
    return bool(flag and Path(flag).exists())


def wait_for_login(process, timeout=300):
    deadline=time.monotonic()+timeout
    while process.poll() is None:
        cancelled=login_cancel_requested()
        if cancelled or time.monotonic()>=deadline:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill();process.wait(timeout=5)
            print('登录已取消，原账号保持不变。' if cancelled else '登录等待超时，原账号保持不变。',flush=True)
            return 130 if cancelled else 124
        time.sleep(0.1)
    return process.wait()


def login_chatgpt(arguments):
    """Authorize separately; preserve old credentials before a successful switch."""
    prefix=[find_codex(),'-c','model_provider="openai"','-c','forced_login_method="chatgpt"','-c','cli_auth_credentials_store="file"']
    # A fresh private home opens authorization without touching the current login.
    # Private application state, outside TEMP: Codex creates PATH helpers here.
    sessions=ROOT/'login-sessions'
    sessions.mkdir(mode=0o700,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='chatgpt-login-',dir=sessions) as folder:
        login_home=Path(folder)
        (login_home/'config.toml').write_text('model_provider = "openai"\nforced_login_method = "chatgpt"\ncli_auth_credentials_store = "file"\n',encoding='utf-8')
        environment=os.environ.copy()
        environment['CODEX_HOME']=str(login_home)
        print('正在打开 ChatGPT 登录授权；原账号会保留，授权成功后才切换。',flush=True)
        if login_cancel_requested():return 130
        process=subprocess.Popen(prefix+['login']+arguments,cwd=ROOT,env=environment)
        result=wait_for_login(process)
        if result:
            print('登录已取消或未完成，原账号保持不变。',flush=True)
            return result
        if login_cancel_requested():return 130
        candidate=login_home/'auth.json'
        try:
            auth=json.loads(candidate.read_text(encoding='utf-8-sig'))
            tokens=auth.get('tokens')
            if auth.get('auth_mode')!='chatgpt' or not isinstance(tokens,dict) or not tokens.get('access_token'):
                raise ValueError('No ChatGPT session')
        except (OSError,ValueError,AttributeError) as exc:
            raise RuntimeError('未获得有效的 ChatGPT 登录信息，原账号保持不变。') from exc
        status=subprocess.run(prefix+['login','status'],cwd=ROOT,env=environment,capture_output=True,timeout=20)
        if status.returncode or b'ChatGPT' not in status.stdout+status.stderr:
            raise RuntimeError('新账号登录验证未通过，原账号保持不变。')
        if login_cancel_requested():return 130
        current=CODEX_HOME/'auth.json'
        if current.exists():
            backup=CODEX_HOME/'account-history'/uuid.uuid4().hex
            backup.mkdir(parents=True,mode=0o700)
            shutil.copy2(current,backup/'auth.json')
        # Same filesystem: switch atomically; the prior file remains in history.
        if login_cancel_requested():return 130
        os.replace(candidate,current)
    for cache in (CODEX_HOME/'models_cache.json',ROOT/'cache/official-model-catalog.json'):
        try:cache.unlink(missing_ok=True)
        except OSError:pass
    print('ChatGPT 登录成功，已切换至本次授权的账号。',flush=True)
    return 0


def main():
    parser=argparse.ArgumentParser(description='pdf2zh-viacodex: PDF translation with official Codex subscription login')
    parser.add_argument('command',choices=['gui','translate','login','logout','models','doctor','bootstrap','test','codex-check','predownload'])
    args,rest=parser.parse_known_args()
    prepare_environment()
    if args.command=='codex-check':
        print(find_codex());return 0
    if args.command=='bootstrap':
        from vendor_isolation import patch_dependencies
        patch_dependencies();print('CACHE ISOLATION PASS');return 0
    if args.command=='predownload':
        from model_assets import preload_models
        preload_models();print('MODEL CACHE PASS');return 0
    if args.command=='login':
        if rest not in ([],['--device-auth']):parser.error('login accepts only --device-auth; API login is disabled')
        return login_chatgpt(rest)
    if args.command=='logout':
        prefix=[find_codex(),'-c','model_provider="openai"','-c','forced_login_method="chatgpt"','-c','cli_auth_credentials_store="file"']
        return subprocess.call(prefix+['logout']+rest,cwd=ROOT)
    if args.command=='models':
        from model_catalog import fetch_models
        print(json.dumps(fetch_models(),ensure_ascii=False,indent=2));return 0
    if args.command=='doctor':
        from vendor_isolation import validate_isolation
        errors=[]
        for name in ('pdf2zh-next','BabelDOC','PyMuPDF'):
            try:print(name+': '+importlib.metadata.version(name))
            except importlib.metadata.PackageNotFoundError:errors.append('Missing dependency: '+name)
        try:validate_isolation();print('Cache isolation: PASS')
        except Exception as exc:errors.append(str(exc))
        try:print('Codex CLI: '+find_codex())
        except Exception as exc:errors.append(str(exc))
        try:
            result=subprocess.run(ensure_chatgpt_auth()+['login','status'],capture_output=True,timeout=20)
            if result.returncode or b'ChatGPT' not in result.stdout+result.stderr:raise RuntimeError('ChatGPT login check failed')
            print('ChatGPT login: PASS')
        except Exception as exc:errors.append(str(exc))
        for error in errors:print('CHECK: '+error)
        print('DOCTOR PASS' if not errors else 'DOCTOR NEEDS ATTENTION')
        return int(bool(errors))
    if args.command=='test':
        return subprocess.call([sys.executable,'-B','-m','unittest','discover','-s',str(PROJECT_ROOT/'tests'),'-v'],cwd=PROJECT_ROOT)
    module='pdf_gui.py' if args.command=='gui' else 'translate_pdf.py'
    return subprocess.call([sys.executable,'-B',str(PROJECT_ROOT/'app'/module)]+rest,cwd=PROJECT_ROOT)

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as exc:
        print(str(exc),file=sys.stderr);sys.exit(1)
