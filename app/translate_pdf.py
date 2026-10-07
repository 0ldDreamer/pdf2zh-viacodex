# SPDX-License-Identifier: AGPL-3.0-or-later
"""Translate source PDFs into Chinese through the native pdf2zh_next CLI engine."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from runtime import ROOT, CODE_ROOT, OUTPUT_ROOT, write_pdf_config, prepare_environment, ensure_chatgpt_auth, translation_profile


def sha256(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def remove_margin_numbers(source, target):
    import fitz
    removed=0
    with fitz.open(source) as document:
        for page in document:
            page_removed=0
            spans=[s for b in page.get_text('dict')['blocks'] if b.get('type')==0
                   for line in b.get('lines',[]) for s in line['spans']]
            body=[s for s in spans if len(s['text'].strip())>20 and s['size']<=14]
            if not body:
                continue
            left=min(s['bbox'][0] for s in body)
            right=max(s['bbox'][2] for s in body)
            groups={}
            for s in spans:
                t=s['text'].strip()
                r=fitz.Rect(s['bbox'])
                if not re.fullmatch(r'\d{1,4}',t) or r.width>26 or s['size']>12:
                    continue
                if not (r.x1<=left-3 or r.x0>=right+3):
                    continue
                groups.setdefault(round(r.x0/6),[]).append((r,int(t)))
            for group in groups.values():
                group.sort(key=lambda v:v[0].y0)
                if len(group)<8 or group[-1][0].y0-group[0][0].y0<80:
                    continue
                steps=[group[i+1][1]-group[i][1] for i in range(len(group)-1)]
                if sum(1<=delta<=5 for delta in steps)/len(steps)<0.85:
                    continue
                for rect,_ in group:
                    page.add_redact_annot(rect+(-0.3,-0.3,0.3,0.3),fill=False)
                    removed+=1
                    page_removed+=1
            if page_removed:
                page.apply_redactions(images=0,graphics=0,text=0)
        document.save(target,garbage=4,deflate=True)
    return removed


def selected_source_pages(spec, count):
    if not spec:
        return list(range(count))
    normalized = re.sub(r'\s+', '', spec.replace('，', ',').replace('、', ',').replace('–', '-'))
    selected = set()
    for item in normalized.split(','):
        if re.fullmatch(r'\d+', item):
            lo = hi = int(item)
        elif re.fullmatch(r'\d*-\d*', item) and item != '-':
            a, b = item.split('-')
            lo, hi = int(a) if a else 1, int(b) if b else count
        else:
            raise ValueError('页码格式示例：1-3 或 1,3,5-7。')
        if lo < 1 or hi < lo or hi > count:
            raise ValueError(f'页码超出范围或顺序不正确，原 PDF 共 {count} 页。')
        selected.update(range(lo - 1, hi))
    return sorted(selected)


def compose_compare(translated, original, indices, target):
    """Place searchable/vector Chinese on the left and untouched original on the right."""
    import fitz
    with fitz.open(translated) as zh, fitz.open(original) as en, fitz.open() as result:
        if len(zh) != len(indices):
            raise RuntimeError('译文与所选原文页数不一致，已停止生成，避免对照页错配。')
        for i, source_index in enumerate(indices):
            left, right = zh[i].rect, en[source_index].rect
            page = result.new_page(width=left.width + right.width, height=max(left.height, right.height))
            if zh[i].get_contents():
                page.show_pdf_page(fitz.Rect(0, 0, left.width, left.height), zh, i)
            if en[source_index].get_contents():
                page.show_pdf_page(fitz.Rect(left.width, 0, left.width + right.width, right.height), en, source_index)
        result.set_metadata({'title': original.stem + ' 中英对照', 'subject': '中文在左，英文原文在右'})
        result.save(target, garbage=4, deflate=True)


def main():
    parser=argparse.ArgumentParser(description='pdf2zh_next + Codex：英文论文译为中文 PDF')
    parser.add_argument('input_pdf',type=Path)
    parser.add_argument('--output-dir',type=Path,help='最终文件保存目录；默认为项目 outputs')
    parser.add_argument('--output-mode', choices=['chinese', 'bilingual', 'both'], default='chinese', help='纯中文、中英对照或两种均生成')
    parser.add_argument('--model',help='官方 model/list 中的模型 ID；首次省略时采用官方默认模型')
    parser.add_argument('--reasoning-effort',help='模型支持的思考强度；省略沿用配置')
    parser.add_argument('--pages',help='原 PDF 页码，例如 1-3；留空翻译全文')
    parser.add_argument('--remove-line-numbers',action='store_true',help='在副本上保守移除外侧连续行号')
    args=parser.parse_args()
    prepare_environment()
    os.chdir(ROOT)
    codex=ensure_chatgpt_auth(sync=True)
    login=subprocess.run(codex+['login','status'],capture_output=True,timeout=30)
    if login.returncode or b'ChatGPT' not in login.stdout+login.stderr:
        raise RuntimeError('ChatGPT 登录验证失败。已停止，未使用 API。')
    source=args.input_pdf.resolve(strict=True)
    if source.suffix.lower()!='.pdf':
        raise ValueError('请选择 PDF 文件。')
    import fitz
    with fitz.open(source) as original:
        if original.needs_pass:
            raise ValueError('请先解锁有密码保护的 PDF。')
        indices = selected_source_pages(args.pages, len(original))
    if not indices:
        raise ValueError('这个 PDF 没有可翻译的页面。')
    if args.pages:
        args.pages = ','.join(str(i + 1) for i in indices)
    profile, profile_id=translation_profile()
    if args.model or args.reasoning_effort or profile['model']=='default':
        from model_catalog import fetch_models, save_translation_selection
        models=fetch_models()['models']
        name=args.model or profile['model']
        if name=='default':name=next((x for x in models if x['is_default']),models[0])['model']
        row=next((x for x in models if x['model']==name),None)
        if row is None:raise ValueError('模型不在官方可用列表中：'+name)
        effort=args.reasoning_effort or profile['model_reasoning_effort']
        if not args.reasoning_effort and effort not in row['efforts']:effort=row['default_effort'] or row['efforts'][0]
        save_translation_selection(name,effort,models)
        profile,profile_id=translation_profile()
    model_filename=re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', profile['model']).rstrip(' .')
    os.environ['PDF2ZH_JOB_PROFILE']=json.dumps(profile)
    codex=ensure_chatgpt_auth()
    original_hash=sha256(source)
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    output_base=(args.output_dir or OUTPUT_ROOT).resolve()
    if output_base.exists() and not output_base.is_dir():
        raise ValueError('保存位置应为文件夹。')
    destination=output_base/(stamp+'_'+source.stem[:65])
    destination.mkdir(parents=True)
    log=destination/'translation.log'
    manifest={'input':str(source),'input_sha256':original_hash,'pages':args.pages or 'all',
              'engine':'pdf2zh-next 2.8.2 -> batched Codex exec', 'batch_size':12, 'batch_concurrency':4,
              'auth':'ChatGPT subscription only','api_fallback':False,'model':profile['model'],'model_reasoning_effort':profile['model_reasoning_effort'],'output_directory':str(output_base),'status':'running','output_mode':args.output_mode,'source_page_indices':[i+1 for i in indices]}
    work=ROOT/'tmp'/stamp
    work.mkdir()
    rendered = work / 'rendered'
    rendered.mkdir()
    input_copy=work/'source.pdf'
    import shutil
    shutil.copy2(source,input_copy)
    manifest['removed_line_numbers']=0
    if args.remove_line_numbers:
        cleaned=work/'cleaned-source.pdf'
        manifest['removed_line_numbers']=remove_margin_numbers(input_copy,cleaned)
        input_copy=cleaned
    command=[sys.executable,str(CODE_ROOT/'pdf2zh_entry.py'),'--config-file',str(write_pdf_config()),
             '--clitranslator','--clitranslator-command', '"'+Path(sys.executable).as_posix()+'" "'+(CODE_ROOT/'codex_translate.py').as_posix()+'"'+' --cache-profile '+profile_id, '--clitranslator-timeout','300','--output',str(rendered),'--lang-in','en','--lang-out','zh',
             '--no-dual','--only-include-translated-page','--watermark-output-mode','no_watermark',
             '--qps','64','--pool-max-workers','64','--no-auto-extract-glossary',str(input_copy)]
    if args.pages:
        command+=['--pages',args.pages]
    print('输出目录：'+str(destination),flush=True)
    os.environ['PDF_CODEX_JOB_DIR']=str(destination)
    print('翻译配置：模型：' + profile['model'] + '；思考强度：' + profile['model_reasoning_effort'] + '；每批最多 12 段，最多 4 批并行。',flush=True)
    print('翻译进度：正在初始化翻译引擎并解析 PDF，请稍候。首次运行可能需要下载版面模型或字体，此阶段可能耗时较长。',flush=True)
    manifest_file=destination/'manifest.json'
    manifest_file.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        with log.open('wb') as output_log:
            result=subprocess.Popen(command,cwd=ROOT,stdout=output_log,stderr=subprocess.STDOUT)
            last_progress=None
            while result.poll() is None:
                progress_file=destination/'progress.json'
                try:
                    progress=json.loads(progress_file.read_text(encoding='utf-8'))
                    summary=(progress['translated'],progress['cache_hits'],progress['active_batches'],progress.get('processed_paragraphs',0),progress.get('total_paragraphs',0))
                    if summary[4] > 0:
                        message=f"翻译进度：段落处理 {summary[3]}/{summary[4]}，新增译文 {summary[0]} 段，缓存 {summary[1]} 段，并行 {summary[2]} 批。"
                    else:
                        message="翻译进度：正在准备翻译，统计段落中……"
                    if message!=last_progress:
                        print(message,flush=True)
                        last_progress=message
                except (OSError,ValueError,KeyError): pass
                time.sleep(1)
            result.wait()
        if (destination/'batch-failed.json').exists():
            raise RuntimeError('批量翻译存在失败段落，已阻止不完整交付。')
        progress_file=destination/'progress.json'
        if progress_file.exists():
            progress=json.loads(progress_file.read_text(encoding='utf-8'))
            manifest['batch_statistics']=progress
            if progress.get('failed_batches',0):
                raise RuntimeError('批量翻译有失败段落，已阻止不完整交付。')
        if sha256(source)!=original_hash:
            raise RuntimeError('原始文件校验异常。')
        pdfs=list(rendered.glob('*.pdf'))
        diagnostics=log.read_text(encoding='utf-8',errors='replace')
        if result.returncode or not pdfs or re.search(r'CLI command failed|CLI command timed out|Error translating file|Translation error:',diagnostics):
            raise RuntimeError('PDF 翻译未完成，请查看日志：'+str(log))
        import fitz
        translated=max(pdfs,key=lambda p:p.stat().st_mtime)
        with fitz.open(translated) as doc:
            text='\n'.join(page.get_text() for page in doc)
            chinese_count=sum('\u4e00'<=c<='\u9fff' for c in text)
            if chinese_count<3:
                raise RuntimeError('生成 PDF 缺少可检索的中文译文。')
            manifest['output_pages']=len(doc)
            manifest['chinese_characters']=chinese_count
        if manifest['output_pages'] != len(indices):
            raise RuntimeError('译文页数与所选原文页数不一致，已停止交付。')
        outputs = []
        if args.output_mode in ('chinese', 'both'):
            final = destination / f"{source.stem}_中文_{model_filename}.pdf"
            shutil.copy2(translated, final)
            outputs.append({'mode':'chinese', 'path':str(final), 'sha256':sha256(final), 'pages':len(indices)})
        if args.output_mode in ('bilingual', 'both'):
            final = destination / f"{source.stem}_中英对照_{model_filename}.pdf"
            compose_compare(translated, source, indices, final)
            outputs.append({'mode':'bilingual', 'path':str(final), 'sha256':sha256(final), 'pages':len(indices), 'left':'zh', 'right':'original'})
        if sha256(source) != original_hash:
            raise RuntimeError('原始文件校验异常。')
        primary = outputs[0]
        manifest.update(status='completed', output=primary['path'], output_sha256=primary['sha256'], outputs=outputs, original_unchanged=True)
        for item in outputs:
            print('完成：' + item['path'], flush=True)
    except Exception as exc:
        manifest.update(status='failed',error=str(exc))
        raise
    finally:
        manifest_file.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print(str(exc),file=sys.stderr)
        sys.exit(1)
