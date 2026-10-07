# SPDX-License-Identifier: AGPL-3.0-or-later
import concurrent.futures
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import runtime
runtime.prepare_environment()
from translate_pdf import selected_source_pages, compose_compare, remove_margin_numbers, sha256
from model_catalog import normalize_models, save_translation_selection
from batch_translate import cache_key, validate_results, BatchManager
import fitz


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=runtime.ROOT/'tmp')
        self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def test_page_ranges_and_pairing(self):
        self.assertEqual(selected_source_pages('4,1,3-4',4),[0,2,3])
        self.assertEqual(selected_source_pages('-2,4-',4),[0,1,3])
        for spec in ['0','5','3-1','-','a']:
            with self.assertRaises(ValueError):selected_source_pages(spec,4)
        source=self.root/'original.pdf';zh=self.root/'translated.pdf';out=self.root/'compare.pdf'
        with fitz.open() as doc:
            for i in range(4):
                p=doc.new_page(width=300,height=400);p.insert_text((25,45),f'ORIGINAL {i+1}')
            doc.save(source)
        with fitz.open() as doc:
            for i in [0,2,3]:
                p=doc.new_page(width=300,height=400);p.insert_text((25,45),f'中文第{i+1}页',fontname='china-s')
            doc.save(zh)
        before=sha256(source)
        compose_compare(zh,source,[0,2,3],out)
        with fitz.open(out) as doc,fitz.open(source) as original:
            self.assertEqual(len(doc),3)
            for i,k in enumerate([0,2,3]):
                page=doc[i]
                self.assertEqual(page.rect.width,600)
                self.assertIn(f'中文第{k+1}页',page.get_text(clip=fitz.Rect(0,0,300,400)).replace(' ',''))
                self.assertIn(f'ORIGINAL {k+1}',page.get_text(clip=fitz.Rect(300,0,600,400)))
                self.assertEqual(page.get_pixmap(clip=fitz.Rect(300,0,600,400)).samples,original[k].get_pixmap().samples)
        self.assertEqual(sha256(source),before)
        with self.assertRaises(RuntimeError):compose_compare(zh,source,[0],self.root/'bad.pdf')

    def test_line_numbers_only_removed_on_copy(self):
        source=self.root/'lines.pdf';clean=self.root/'clean.pdf'
        with fitz.open() as doc:
            p=doc.new_page(width=500,height=500)
            for i in range(12):
                p.insert_text((5,70+i*20),str(i+1),fontsize=9)
                p.insert_text((70,70+i*20),'Cognitive diagnosis retains citation [12] and value 0.83.',fontsize=10)
            doc.save(source)
        before=sha256(source)
        self.assertEqual(remove_margin_numbers(source,clean),12)
        self.assertEqual(sha256(source),before)
        with fitz.open(clean) as doc:
            self.assertIn('[12]',doc[0].get_text());self.assertIn('0.83',doc[0].get_text())

    def test_auth_rejects_api_mode(self):
        (self.root/'auth.json').write_text(json.dumps({'auth_mode':'apikey','OPENAI_API_KEY':'unit-fixture-not-a-real-key'}))
        with patch.object(runtime,'CODEX_HOME',self.root):
            with self.assertRaises(RuntimeError):runtime.ensure_chatgpt_auth()

    def test_official_models_and_effort_validation(self):
        rows=[{'model':'unit-model','supportedReasoningEfforts':[{'reasoningEffort':'unit-low'},{'reasoningEffort':'unit-high'}],'defaultReasoningEffort':'unit-low','isDefault':True}]
        models=normalize_models(rows)
        self.assertEqual(models[0]['efforts'],['unit-low','unit-high'])
        from model_catalog import CODEX_HOME
        (self.root/'config.toml').write_text('model_provider="openai"\n')
        with patch('model_catalog.CODEX_HOME',self.root),patch('runtime.CODEX_HOME',self.root),patch('model_catalog.write_pdf_config'):
            saved=save_translation_selection('unit-model','unit-low',models)
            self.assertEqual(saved['model'],'unit-model')
            self.assertEqual(saved['model_reasoning_effort'],'unit-low')
            with self.assertRaises(ValueError):save_translation_selection('other','unit-low',models)
            with self.assertRaises(ValueError):save_translation_selection('unit-model','unsupported',models)

    def test_placeholders_and_profile_separation(self):
        good={'p0':'中文 {v1} <style id="2">公式</style> [12] 0.83'}
        src={'p0':'English {v1} <style id="2">formula</style> [12] 0.83'}
        self.assertEqual(validate_results(src,good),good)
        for bad in [{'p0':'中文'}, {}, {'p0':''}]:
            with self.assertRaises(RuntimeError):validate_results(src,bad)
        self.assertNotEqual(cache_key('same',{'model':'m','effort':'low'}),cache_key('same',{'model':'m','effort':'high'}))

    def test_batch_producers_supply_eight_full_batches(self):
        from translation_settings import BATCH_SIZE, CONCURRENCY, PARAGRAPH_WORKERS
        profile={'model':'unit-model','model_reasoning_effort':'low','model_provider':'openai'}
        all_running=threading.Event()
        release=threading.Event()
        lock=threading.Lock()
        active=peak=0
        def runner(sources,identifier):
            nonlocal active,peak
            with lock:
                active+=1
                peak=max(peak,active)
                if active==CONCURRENCY:all_running.set()
            if not release.wait(10):raise RuntimeError('producer queue stalled')
            with lock:active-=1
            return {key:'译文 '+value for key,value in sources.items()},{}
        texts=[f'unique paragraph {i} {{v1}}' for i in range(BATCH_SIZE*CONCURRENCY)]
        with patch('batch_translate.translation_codex',return_value=['unit-codex']),patch('batch_translate.translation_profile',return_value=(profile,'unit')):
            manager=BatchManager(job_dir=self.root/'parallel',runner=runner,cache_path=self.root/'parallel.db')
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=PARAGRAPH_WORKERS) as producers:
                    futures=[producers.submit(manager.translate,text) for text in texts]
                    try:
                        self.assertTrue(all_running.wait(10),'paragraph producers could not fill all batch consumers')
                        self.assertEqual(peak,CONCURRENCY)
                        self.assertEqual(manager.stats['active_batches'],CONCURRENCY)
                    finally:release.set()
                    results=[future.result(timeout=10) for future in futures]
                self.assertEqual(results,['译文 '+text for text in texts])
                self.assertEqual(manager.stats['translated'],len(texts))
                self.assertEqual(manager.stats['failed_batches'],0)
                self.assertEqual(manager.translate(texts[0]),results[0])
                self.assertEqual(manager.stats['cache_hits'],1)
            finally:
                release.set()
                manager.pool.shutdown(wait=True)

    def test_batch_deduplication_cache_and_failure_guard(self):
        profile={'model':'unit-model','model_reasoning_effort':'low','model_provider':'openai'}
        calls=[]
        def runner(sources,identifier):
            calls.append(sources);return {key:'译文 '+value for key,value in sources.items()},{}
        with patch('batch_translate.translation_codex',return_value=['unit-codex']),patch('batch_translate.translation_profile',return_value=(profile,'unit')):
            manager=BatchManager(job_dir=self.root/'job',runner=runner,cache_path=self.root/'cache.db')
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                results=list(pool.map(manager.translate,['sample {v1}']*8))
            self.assertEqual(len(set(results)),1);self.assertEqual(len(calls),1)
            self.assertEqual(manager.translate('sample {v1}'),results[0]);self.assertEqual(len(calls),1)
            self.assertEqual(manager.stats['failed_batches'],0)
            manager.pool.shutdown(wait=True)
            failed=BatchManager(job_dir=self.root/'failed',runner=lambda sources,i:({},{}),cache_path=self.root/'fail-cache.db')
            with self.assertRaises(RuntimeError):failed.translate('must translate {v1}')
            self.assertTrue((self.root/'failed/batch-failed.json').is_file())
            failed.pool.shutdown(wait=True)


if __name__=='__main__':unittest.main()
