# SPDX-License-Identifier: AGPL-3.0-or-later
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from runtime import ROOT,prepare_environment
prepare_environment()

@unittest.skipUnless(os.name=='nt' or os.environ.get('DISPLAY'),'GUI requires a desktop session')
class GuiTests(unittest.TestCase):
    def setUp(self):
        self.settings_temp=tempfile.TemporaryDirectory(dir=ROOT/'tmp')
        self.settings_patch=patch('pdf_gui.SETTINGS',Path(self.settings_temp.name)/'gui-settings.json')
        self.settings_patch.start()

    def tearDown(self):
        self.settings_patch.stop()
        self.settings_temp.cleanup()

    def test_stop_resume_and_dynamic_efforts(self):
        import tkinter as tk
        import fitz
        from pdf_gui import TranslationWindow,build_command
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            source=Path(folder)/'input.pdf'
            with fitz.open() as doc:
                doc.new_page();doc.save(source)
            w=tk.Tk();app=TranslationWindow(w,str(source),refresh_catalog=False)
            try:
                app.apply_catalog({'models':[{'model':'unit','efforts':['low','medium'],'default_effort':'low','is_default':True}],'checked_at':''})
                app.model.set('unit');app.reasoning_effort.set('invalid');app.sync_efforts()
                self.assertEqual(app.reasoning_effort.get(),'low')
                self.assertEqual(list(app.effort_box.cget('values')),['low','medium'])
                commands=[];app.run_worker=lambda command:commands.append(list(command));app.save_settings=lambda:None
                with patch('pdf_gui.save_translation_selection'):
                    app.start();w.update()
                    for _ in range(30):
                        if commands:break
                        time.sleep(.01)
                    self.assertTrue(app.busy);self.assertEqual(app.stop_button.cget('text'),'停止')
                    command=commands[0]
                    app.finish(1,True);w.update()
                    self.assertEqual(app.stop_button.cget('text'),'继续')
                    app.pdf.set('changed.pdf')
                    app.reasoning_effort.set('medium')
                    app.stop_button.invoke();w.update()
                    for _ in range(30):
                        if len(commands)>1:break
                        time.sleep(.01)
                    self.assertEqual(commands[1],command)
                    self.assertEqual(app.pdf.get(),str(source))
                    self.assertEqual(app.reasoning_effort.get(),'medium')
                    self.assertFalse(app.cancel_requested.is_set())
                    app.finish(1,True)
                app.events.put(('models_error','unit failure'));app.poll()
                self.assertIn('缓存',app.catalog_status.get())
                with self.assertRaises(ValueError):build_command(str(source),False,'',False,None,False,False)
                # CI's desktop can cap Tk windows at 751px. Explicitly allow
                # the requested test sizes before checking layout at 820+px.
                w.maxsize(1200,1200)
                for width,height in [(1000,848),(860,820)]:
                    w.geometry(f'{width}x{height}');w.update()
                    self.assertEqual(w.winfo_height(),height)
                    self.assertGreaterEqual(app.activity.winfo_height(),180)
                    for control in app.controls + [app.model_box,app.effort_box,app.login_button,app.start_button,app.stop_button]:
                        self.assertTrue(control.winfo_ismapped())
                        right=control.winfo_rootx()-w.winfo_rootx()+control.winfo_width()
                        self.assertLessEqual(right,width)
                        bottom=control.winfo_rooty()-w.winfo_rooty()+control.winfo_height()
                        self.assertLessEqual(bottom,height)
            finally:w.destroy()

    def test_login_blocks_translation_until_authorization_completes(self):
        import tkinter as tk
        from pdf_gui import TranslationWindow
        w=tk.Tk();app=TranslationWindow(w,refresh_catalog=False)
        try:
            app.catalog_loading=False
            app.login_in_progress=True
            app.sync_model_controls()
            self.assertEqual(str(app.start_button.cget('state')),'disabled')
            self.assertEqual(str(app.model_box.cget('state')),'disabled')
            with patch('pdf_gui.build_command') as build:
                app.start()
                build.assert_not_called()
            app.refresh_models=Mock()
            app.note=Mock()
            app.events.put(('login_done',0));app.poll()
            self.assertFalse(app.login_in_progress)
            self.assertEqual(app.models,[])
            self.assertIn('已切换',app.status.get())
            app.refresh_models.assert_called_once()
            app.login_in_progress=True
            app.events.put(('login_done',1));app.poll()
            self.assertIn('原账号保留',app.status.get())
        finally:w.destroy()

    def test_cancel_login_button_and_timeout_restore_controls(self):
        import tkinter as tk
        from pdf_gui import TranslationWindow
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            w=tk.Tk();app=TranslationWindow(w,refresh_catalog=False)
            try:
                app.catalog_loading=False
                app.paused_command=['unit'];app.paused_settings={'unit':True}
                app.login_in_progress=True
                app.login_cancel_file=Path(folder)/'cancel'
                app.sync_model_controls()
                self.assertEqual(app.login_button.cget('text'),'取消登录')
                self.assertEqual(str(app.login_button.cget('state')),'normal')
                for button in (app.refresh_models_button,app.start_button,app.stop_button):
                    self.assertEqual(str(button.cget('state')),'disabled')
                with patch('pdf_gui.fetch_models') as fetch:
                    app.refresh_models();fetch.assert_not_called()
                app.login_button.invoke()
                self.assertTrue(app.login_cancel_file.exists())
                self.assertTrue(app.login_cancel_requested.is_set())
                app.events.put(('login_done',130));app.poll()
                self.assertFalse(app.login_in_progress)
                self.assertEqual(app.login_button.cget('text'),'切换账号' if app.logged_in else '登录 ChatGPT')
                self.assertIn('已取消',app.status.get())
                for button in (app.refresh_models_button,app.start_button,app.stop_button):
                    self.assertEqual(str(button.cget('state')),'normal')
                app.login_in_progress=True
                app.events.put(('login_done',124));app.poll()
                self.assertFalse(app.login_in_progress)
                self.assertIn('5 分钟',app.status.get())
                self.assertEqual(str(app.refresh_models_button.cget('state')),'normal')
            finally:w.destroy()

    def test_log_expands_on_small_desktop(self):
        import tkinter as tk
        from pdf_gui import TranslationWindow
        w=tk.Tk();app=TranslationWindow(w,refresh_catalog=False)
        try:
            # Reproduce the cloud runner's actual window-height constraint.
            w.minsize(860,640);w.maxsize(1000,751)
            w.geometry('1000x848');w.update()
            self.assertEqual(w.winfo_height(),751)
            initial=app.activity.winfo_height()
            self.assertGreater(initial,0)
            self.assertTrue(app.log_scrollbar.winfo_ismapped())
            app.expand_log_button.invoke();w.update()
            self.assertTrue(app.log_expanded)
            self.assertFalse(app.file_box.winfo_ismapped())
            self.assertFalse(app.options_box.winfo_ismapped())
            self.assertGreater(app.activity.winfo_height(),initial)
            self.assertGreaterEqual(app.activity.winfo_height(),180)
            app.expand_log_button.invoke();w.update()
            self.assertFalse(app.log_expanded)
            self.assertTrue(app.file_box.winfo_ismapped())
            self.assertTrue(app.options_box.winfo_ismapped())
            self.assertEqual(app.activity.winfo_height(),initial)
        finally:w.destroy()

    def test_account_badge_tracks_saved_login_and_keeps_old_account_on_cancel(self):
        import json
        import tkinter as tk
        from pdf_gui import TranslationWindow,has_chatgpt_session
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder, patch('pdf_gui.CODEX_HOME',Path(folder)):
            auth=Path(folder)/'auth.json'
            self.assertFalse(has_chatgpt_session())
            w=tk.Tk();app=TranslationWindow(w,refresh_catalog=False)
            try:
                self.assertEqual(app.account_status.get(),'○ 未登录')
                self.assertEqual(app.login_button.cget('text'),'登录 ChatGPT')
                for invalid in ['broken json','[]',json.dumps({'auth_mode':'apikey'}),json.dumps({'auth_mode':'chatgpt','tokens':{}})]:
                    auth.write_text(invalid)
                    self.assertFalse(has_chatgpt_session())
                fixture={'auth_mode':'chatgpt','tokens':{'access_token':'unit-test-not-a-real-token'}}
                auth.write_text(json.dumps(fixture))
                app.refresh_models=Mock()
                app.events.put(('login_done',0));app.poll()
                self.assertEqual(app.account_status.get(),'● 已登录')
                self.assertEqual(app.login_button.cget('text'),'切换账号')
                before=auth.read_bytes()
                for code in [130,124,1]:
                    app.login_in_progress=True
                    app.sync_model_controls()
                    self.assertEqual(app.login_button.cget('text'),'取消登录')
                    app.events.put(('login_done',code));app.poll()
                    self.assertEqual(app.account_status.get(),'● 已登录')
                    self.assertEqual(app.login_button.cget('text'),'切换账号')
                    self.assertEqual(auth.read_bytes(),before)
                previous=app.output_chinese.get()
                app.chinese_check.invoke()
                self.assertEqual(app.output_chinese.get(),not previous)
                app.chinese_check.invoke()
                self.assertEqual(app.output_chinese.get(),previous)
            finally:w.destroy()

    def test_pdf_picker_remembers_folder_after_restart_and_ignores_cancel(self):
        import json
        import tkinter as tk
        import fitz
        from pdf_gui import TranslationWindow,PROJECT_ROOT
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            state=Path(folder)
            papers=state/'中文 论文';papers.mkdir()
            source=papers/'paper.pdf'
            with fitz.open() as doc:
                doc.new_page();doc.save(source)
            settings=state/'settings.json'
            with patch('pdf_gui.SETTINGS',settings):
                w=tk.Tk();app=TranslationWindow(w,refresh_catalog=False)
                try:
                    app.remember.set(False)
                    with patch('pdf_gui.filedialog.askopenfilename',return_value=str(source)) as choose:
                        app.browse()
                    self.assertEqual(choose.call_args.kwargs['initialdir'],str(PROJECT_ROOT))
                    self.assertEqual(json.loads(settings.read_text(encoding='utf-8')),{'last_pdf_directory':str(papers.resolve())})
                finally:w.destroy()
                w=tk.Tk();app=TranslationWindow(w,refresh_catalog=False)
                try:
                    before=settings.read_bytes()
                    with patch('pdf_gui.filedialog.askopenfilename',return_value='') as choose:
                        app.browse()
                    self.assertEqual(choose.call_args.kwargs['initialdir'],str(papers.resolve()))
                    self.assertEqual(settings.read_bytes(),before)
                    source.unlink();papers.rmdir()
                    with patch('pdf_gui.filedialog.askopenfilename',return_value='') as choose:
                        app.browse()
                    self.assertEqual(choose.call_args.kwargs['initialdir'],str(PROJECT_ROOT))
                finally:w.destroy()
