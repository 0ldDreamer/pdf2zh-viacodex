# SPDX-License-Identifier: AGPL-3.0-or-later
"""Create an allowlisted source-only ZIP, never include runtime accounts/documents."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]
FILES=['README.md','LICENSE','THIRD_PARTY_NOTICES.md','CHANGELOG.md','CONTRIBUTING.md','.gitignore','.gitattributes','requirements.txt','project.py',
       '安装依赖.cmd','登录ChatGPT.cmd','翻译PDF.cmd','检查环境.cmd','app/translation_instructions.md']
PATTERNS=['app/*.py','scripts/*.py','scripts/*.ps1','tests/*.py','docs/*.md','docs/images/*.png','.github/workflows/*.yml']


def source_files():
    files=[ROOT/name for name in FILES]
    for pattern in PATTERNS:files.extend(ROOT.glob(pattern))
    files=sorted(set(files))
    for path in files:
        if not path.is_file():raise RuntimeError('Required release file missing: '+str(path.relative_to(ROOT)))
        relative=path.relative_to(ROOT)
        if any(x in relative.parts for x in ('.runtime','.venv','outputs','.git')):raise RuntimeError('Runtime file in source list')
        if path.suffix.lower() in ('.md','.py','.ps1','.cmd','.yml','.txt'):
            text=path.read_text(encoding='utf-8-sig')
            if re.search(r'(?:sk-[A-Za-z0-9_-]{20,}|eyJ[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{20,}\.)',text):
                raise RuntimeError('Possible credential detected: '+str(relative))
            if re.search(r'[A-Za-z]:[\\/]+(?:Research_Workspace|Users[\\/]+[^\\/\s]+[\\/]+(?:AppData|\.codex))', text):
                raise RuntimeError('Personal machine path detected: '+str(relative))
    return files


def main():
    files=source_files()
    output=ROOT/'outputs/releases';output.mkdir(parents=True,exist_ok=True)
    archive=output/'pdf2zh-viacodex-v1.0-source.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in files:bundle.write(path,Path('pdf2zh-viacodex')/path.relative_to(ROOT))
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip():raise RuntimeError('Source archive integrity check failed')
        names=bundle.namelist()
        if any('/.runtime/' in n or '/.venv/' in n or n.endswith('auth.json') for n in names):raise RuntimeError('Private files in archive')
    report={'archive':str(archive),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'source_file_count':len(files),'runtime_and_accounts_excluded':True}
    (output/'release-manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
