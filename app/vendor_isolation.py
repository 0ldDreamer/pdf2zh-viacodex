# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reproducible cache-path adaptation of pinned dependencies in a dedicated venv."""
from pathlib import Path
import importlib.metadata
import re
import sysconfig

PATCHES = [
    ('babeldoc/const.py','CACHE_FOLDER','BABELDOC_CACHE_DIR','babeldoc'),
    ('pdf2zh_next/const.py','DEFAULT_CONFIG_DIR','PDF2ZH_CONFIG_DIR','config'),
    ('pdf2zh_next/translator/cache.py','cache_folder','PDF2ZH_CACHE_DIR','pdf2zh_next'),
]


def patch_dependencies():
    expected={'pdf2zh-next':'2.8.2','BabelDOC':'0.5.24'}
    for name,version in expected.items():
        if importlib.metadata.version(name)!=version:
            raise RuntimeError('依赖版本不一致，请使用 requirements.txt 重新安装。')
    site=Path(sysconfig.get_paths()['purelib'])
    for relative,var,env,fallback in PATCHES:
        path=site/relative;text=path.read_text(encoding='utf-8')
        expression=f'{var} = Path(__import__("os").environ["{env}"])  # pdf2zh-viacodex isolation'
        text,n=re.subn(r'(?m)^(\s*)'+var+r'\s*=.*$',lambda m:m.group(1)+expression,text,count=1)
        if n!=1:raise RuntimeError('依赖布局不兼容：'+relative)
        path.write_text(text,encoding='utf-8')
    return validate_isolation()


def validate_isolation():
    site=Path(sysconfig.get_paths()['purelib'])
    for relative,_,env,_ in PATCHES:
        path=site/relative
        if not path.exists() or 'pdf2zh-viacodex isolation' not in path.read_text(encoding='utf-8'):
            raise RuntimeError('缓存隔离未安装或被依赖升级覆盖，请重新运行安装依赖.cmd。')
    return True
