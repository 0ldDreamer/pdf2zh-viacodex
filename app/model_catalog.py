# SPDX-License-Identifier: AGPL-3.0-or-later
"""Discover models and their advertised reasoning options using official Codex app-server."""
import datetime
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
import uuid
from runtime import ROOT, CODEX_HOME, prepare_environment, ensure_chatgpt_auth, translation_profile, write_pdf_config

CATALOG_FILE = ROOT / 'cache' / 'official-model-catalog.json'


def normalize_models(rows):
    result = []
    seen = set()
    for row in rows:
        model = row.get('model') or row.get('id')
        if not isinstance(model, str) or not model or row.get('hidden') or model in seen:
            continue
        if 'text' not in row.get('inputModalities', ['text']):
            continue
        efforts = [x['reasoningEffort'] for x in row.get('supportedReasoningEfforts', []) if isinstance(x, dict) and isinstance(x.get('reasoningEffort'), str)]
        efforts = list(dict.fromkeys(efforts))
        if not efforts:
            continue
        result.append({'model':model,'display_name':row.get('displayName') or model,
                       'efforts':efforts,'default_effort':row.get('defaultReasoningEffort'),
                       'is_default':bool(row.get('isDefault'))})
        seen.add(model)
    if not result:
        raise RuntimeError('官方未返回可用于文本翻译且包含思考强度选项的模型。')
    return result


def fetch_models(timeout=40, force_refresh=True):
    prepare_environment()
    try:
        before_fetch = json.loads((CODEX_HOME / 'models_cache.json').read_text(encoding='utf-8')).get('fetched_at')
    except (OSError, ValueError):
        before_fetch = None
    command = ensure_chatgpt_auth(sync=True) + ['app-server']
    incoming = queue.Queue()
    upstream_cache = CODEX_HOME / 'models_cache.json'
    backup = CODEX_HOME / ('models-cache-refresh-' + uuid.uuid4().hex + '.json')
    if force_refresh and upstream_cache.exists():
        upstream_cache.replace(backup)
    # stderr is discarded: do not expose auth diagnostics or credentials in the UI.
    try:
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
                                   creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except Exception:
        if backup.exists():backup.replace(upstream_cache)
        raise
    def read():
        try:
            for line in process.stdout:
                try:incoming.put(json.loads(line))
                except ValueError:pass
        finally:incoming.put(None)
    reader = threading.Thread(target=read, daemon=True);reader.start()
    deadline = time.monotonic() + timeout
    request_id = 0
    def send(message):
        process.stdin.write(json.dumps(message) + '\n');process.stdin.flush()
    def request(method, params):
        nonlocal request_id
        request_id += 1
        send({'id':request_id,'method':method,'params':params})
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:raise TimeoutError('获取官方模型列表超时，请点击“刷新模型”重试。')
            try:message = incoming.get(timeout=remaining)
            except queue.Empty:raise TimeoutError('获取官方模型列表超时，请重试。')
            if message is None:raise RuntimeError('Codex 模型服务已退出，未获取到列表。')
            if message.get('id') != request_id:continue
            if 'error' in message:raise RuntimeError('官方模型服务请求失败，请检查 Codex 登录后刷新。')
            return message.get('result', {})
    try:
        request('initialize', {'clientInfo':{'name':'pdf_translation_model_picker','title':'PDF Translation','version':'1.0'}})
        send({'method':'initialized','params':{}})
        rows=[];cursor=None;seen_cursors=set()
        while True:
            params={'limit':100,'includeHidden':False}
            if cursor:params['cursor']=cursor
            response = request('model/list',params)
            rows.extend(response.get('data',[]))
            cursor=response.get('nextCursor')
            if not cursor:break
            if cursor in seen_cursors:raise RuntimeError('官方列表分页异常。')
            seen_cursors.add(cursor)
        catalog={'source':'Codex app-server model/list','checked_at':datetime.datetime.now().astimezone().isoformat(), 'models':normalize_models(rows)}
        # Codex may internally use its last official catalog when offline.
        upstream_cache = CODEX_HOME / 'models_cache.json'
        try:
            upstream=json.loads(upstream_cache.read_text(encoding='utf-8'))
            catalog['official_fetched_at']=upstream.get('fetched_at')
            catalog['remote_refreshed']=bool(catalog['official_fetched_at'] and catalog['official_fetched_at'] != before_fetch)
        except (OSError,ValueError):pass
        if force_refresh and not catalog.get('remote_refreshed'):
            raise RuntimeError('未能获取新的官方模型目录，请检查网络后刷新；继续使用之前的官方缓存。')
        temporary=CATALOG_FILE.with_suffix('.tmp')
        temporary.write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(CATALOG_FILE)
        return catalog
    finally:
        if process.stdin:process.stdin.close()
        try:process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill();process.wait(timeout=3)
        process.stdout.close()
        if backup.exists():
            if not upstream_cache.exists():backup.replace(upstream_cache)
            else:backup.unlink()


def load_cached_models():
    try:
        data=json.loads(CATALOG_FILE.read_text(encoding='utf-8'))
        if data.get('source')=='Codex app-server model/list' and data.get('models'):
            return data
    except (OSError,ValueError):pass
    return None


def save_translation_selection(model, effort, models):
    advertised=next((x for x in models if x['model']==model),None)
    if not advertised or effort not in advertised['efforts']:
        raise ValueError('请选择官方列表中的模型及其支持的思考强度。')
    config_path=CODEX_HOME/'config.toml'
    text=config_path.read_text(encoding='utf-8-sig')
    for key,value in [('model',model),('model_reasoning_effort',effort)]:
        text,count=re.subn(r'(?m)^'+key+r'\s*=\s*[^\n]+',key+' = '+json.dumps(value),text)
        if count==0:text += '\n'+key+' = '+json.dumps(value)+'\n'
        elif count!=1:raise RuntimeError('独立翻译配置有重复设置项：'+key)
    temporary=config_path.with_suffix('.tmp')
    temporary.write_text(text,encoding='utf-8');temporary.replace(config_path)
    profile,profile_id=translation_profile()
    write_pdf_config()
    return profile


if __name__=='__main__':
    result=fetch_models()
    print(json.dumps(result,ensure_ascii=False,indent=2))
