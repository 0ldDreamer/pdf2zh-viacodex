# SPDX-License-Identifier: AGPL-3.0-or-later
"""Portable project paths, isolated environment and official ChatGPT-only authentication."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
from translation_settings import PARAGRAPH_WORKERS, PARAGRAPH_QPS

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODE_ROOT = PROJECT_ROOT / 'app'
ROOT = Path(os.environ.get('PDF2ZH_VIACODEX_STATE_DIR', str(PROJECT_ROOT / '.runtime'))).expanduser().resolve()
OUTPUT_ROOT = PROJECT_ROOT / 'outputs'
CODEX_HOME = ROOT / 'codex-home'


def prepare_environment():
    paths = {
        'TEMP': ROOT/'tmp', 'TMP': ROOT/'tmp', 'TMPDIR': ROOT/'tmp',
        'XDG_CACHE_HOME':ROOT/'cache', 'XDG_CONFIG_HOME':ROOT/'config',
        'HF_HOME':ROOT/'cache/huggingface', 'HUGGINGFACE_HUB_CACHE':ROOT/'cache/huggingface/hub',
        'TORCH_HOME':ROOT/'cache/torch','MODELSCOPE_CACHE':ROOT/'cache/modelscope',
        'BABELDOC_CACHE_DIR':ROOT/'cache/babeldoc', 'UV_CACHE_DIR':ROOT/'cache/uv',
        'PIP_CACHE_DIR':ROOT/'cache/pip','GRADIO_TEMP_DIR':ROOT/'tmp/gradio',
        'PYTHONPYCACHEPREFIX':ROOT/'cache/pycache','CODEX_HOME':CODEX_HOME,
        'PDF2ZH_CONFIG_DIR':ROOT/'config/pdf2zh','PDF2ZH_CACHE_DIR':ROOT/'cache/pdf2zh_next',
    }
    for key,value in paths.items():
        value.mkdir(parents=True,exist_ok=True);os.environ[key]=str(value)
    (ROOT/'logs').mkdir(parents=True,exist_ok=True)
    os.environ['PYTHONUTF8']='1';os.environ['PYTHONDONTWRITEBYTECODE']='1'
    os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
    for key in ('OPENAI_API_KEY','CODEX_API_KEY','CODEX_ACCESS_TOKEN','OPENAI_BASE_URL','OPENAI_API_BASE','AZURE_OPENAI_API_KEY'):
        os.environ.pop(key,None)
    # Children use the same code even when spawned by pdf2zh on Windows.
    os.environ['PYTHONPATH']=str(CODE_ROOT)+os.pathsep+os.environ.get('PYTHONPATH','')
    config=CODEX_HOME/'config.toml'
    if not config.exists():
        config.write_text('model_provider = "openai"\nmodel_reasoning_effort = "low"\nforced_login_method = "chatgpt"\ncli_auth_credentials_store = "file"\napproval_policy = "never"\nsandbox_mode = "read-only"\n',encoding='utf-8')
    # Restrict account storage to the current OS user where supported.
    if os.name!='nt':CODEX_HOME.chmod(0o700)


def translation_profile():
    pinned=os.environ.get('PDF2ZH_JOB_PROFILE')
    if pinned:
        profile=json.loads(pinned)
        encoded=json.dumps(profile,sort_keys=True,ensure_ascii=False)
        return profile,hashlib.sha256(encoded.encode()).hexdigest()[:20]
    config=tomllib.loads((CODEX_HOME/'config.toml').read_text(encoding='utf-8-sig'))
    profile={'model':config.get('model','default'),'model_reasoning_effort':config.get('model_reasoning_effort','default'),'model_provider':'openai'}
    encoded=json.dumps(profile,sort_keys=True,ensure_ascii=False)
    return profile,hashlib.sha256(encoded.encode()).hexdigest()[:20]


def find_codex():
    explicit=os.environ.get('PDF2ZH_CODEX_EXE')
    if explicit:
        path=Path(explicit).expanduser().resolve(strict=True)
        if not path.is_file():raise RuntimeError('PDF2ZH_CODEX_EXE 必须是可执行文件。')
        return str(path)
    candidates=list((ROOT/'tools/node_modules').glob('**/codex.exe')) if os.name=='nt' else []
    candidates=[p for p in candidates if p.is_file()]
    if candidates:return str(candidates[0])
    found=shutil.which('codex.exe') or shutil.which('codex')
    if found and Path(found).suffix.lower() not in ('.cmd','.ps1'):return found
    if os.name=='nt' and os.environ.get('LOCALAPPDATA'):
        candidates=list((Path(os.environ['LOCALAPPDATA'])/'OpenAI/Codex/bin').glob('*/codex.exe'))
        if candidates:return str(max(candidates,key=lambda p:p.stat().st_mtime))
    if found:return found
    raise RuntimeError('找不到官方 Codex CLI。请运行安装依赖.cmd，或安装官方 Codex CLI 后重试。')


def ensure_chatgpt_auth(sync=False):
    # No implicit import from another app/account; each installation logs in independently.
    target=CODEX_HOME/'auth.json'
    if not target.exists():raise RuntimeError('请先点击“登录 ChatGPT”或运行 登录ChatGPT.cmd。')
    auth=json.loads(target.read_text(encoding='utf-8-sig'))
    if auth.get('auth_mode')!='chatgpt' or not auth.get('tokens'):
        raise RuntimeError('只允许 ChatGPT 官方登录，已阻止 API Key 模式。')
    command=[find_codex(),'-c','model_provider="openai"','-c','forced_login_method="chatgpt"','-c','cli_auth_credentials_store="file"']
    profile,_=translation_profile()
    if profile['model']!='default':command += ['-c','model='+json.dumps(profile['model'])]
    if profile['model_reasoning_effort']!='default':command += ['-c','model_reasoning_effort='+json.dumps(profile['model_reasoning_effort'])]
    return command


def translation_codex():
    # Translation needs neither the coding-agent instructions nor its tool catalog.
    # Apply this to translation subprocesses only; login and model/list stay unchanged.
    return ensure_chatgpt_auth() + [
        '-c','model_provider="pdf-https"',
        '-c','model_providers.pdf-https.name="OpenAI HTTPS"',
        '-c','model_providers.pdf-https.requires_openai_auth=true',
        '-c','model_providers.pdf-https.wire_api="responses"',
        '-c','model_providers.pdf-https.supports_websockets=false',
        '-c','model_instructions_file='+json.dumps(str(CODE_ROOT/'translation_instructions.md')),
        '-c','features.apps=false', '-c','features.plugins=false',
        '-c','features.shell_tool=false',
    ]


def write_pdf_config():
    _,profile_id=translation_profile()
    command='"'+Path(sys.executable).as_posix()+'" "'+(CODE_ROOT/'codex_translate.py').as_posix()+'" --cache-profile '+profile_id
    text=f'clitranslator = true\n[translation]\nlang_in = "en"\nlang_out = "zh"\nqps = {PARAGRAPH_QPS}\npool_max_workers = {PARAGRAPH_WORKERS}\nno_auto_extract_glossary = true\n[pdf]\nno_dual = true\nonly_include_translated_page = true\nwatermark_output_mode = "no_watermark"\n[clitranslator_detail]\nclitranslator_timeout = 300\nclitranslator_command = '+json.dumps(command)+'\n'
    path=ROOT/'config/pdf2zh-codex.toml';path.write_text(text,encoding='utf-8')
    return path


def open_file(path):
    if os.name=='nt':os.startfile(path)
    elif sys.platform=='darwin':subprocess.Popen(['open',str(path)])
    else:subprocess.Popen(['xdg-open',str(path)])
