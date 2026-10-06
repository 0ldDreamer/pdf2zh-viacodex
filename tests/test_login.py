# SPDX-License-Identifier: AGPL-3.0-or-later
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / 'app'))
from runtime import ROOT, prepare_environment
prepare_environment()
spec = importlib.util.spec_from_file_location('project_login_entry', PROJECT_ROOT / 'project.py')
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class LoginTests(unittest.TestCase):
    def exercise_login(self, existing=True, login_code=0, new_auth='valid', verify_code=0,
                       failure=None, replacement_error=False, device=False, previous_mode='chatgpt'):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            state=Path(folder)
            (state/'tmp').mkdir()
            (state/'cache').mkdir()
            home=state/'codex-home';home.mkdir()
            current=home/'auth.json'
            previous=json.dumps({'auth_mode':previous_mode,'tokens':{'access_token':'unit-original'}}).encode()
            replacement=json.dumps({'auth_mode':'chatgpt','tokens':{'access_token':'unit-new'}}).encode()
            if existing:current.write_bytes(previous)
            (home/'config.toml').write_text('model="unit-original-model"',encoding='utf-8')
            caches=[home/'models_cache.json',state/'cache/official-model-catalog.json']
            for cache in caches:cache.write_text('original-cache',encoding='utf-8')
            staging=[]
            def authorize(command,**options):
                self.assertEqual(command[-2:] if device else command[-1:],['login','--device-auth'] if device else ['login'])
                self.assertNotIn('logout',command)
                temporary=Path(options['env']['CODEX_HOME']);staging.append(temporary)
                self.assertNotEqual(temporary,home)
                self.assertTrue(temporary.is_relative_to(state/'login-sessions'))
                self.assertFalse(temporary.is_relative_to(state/'tmp'))
                self.assertFalse((temporary/'auth.json').exists())
                if existing:self.assertEqual(current.read_bytes(),previous)
                if new_auth=='valid':(temporary/'auth.json').write_bytes(replacement)
                elif new_auth=='invalid':(temporary/'auth.json').write_text('{"auth_mode":"apikey"}',encoding='utf-8')
                process=Mock()
                process.poll.return_value=login_code
                process.wait.return_value=login_code
                return process
            def verify(command,**options):
                self.assertEqual(command[-2:],['login','status'])
                self.assertEqual(Path(options['env']['CODEX_HOME']),staging[0])
                if existing:self.assertEqual(current.read_bytes(),previous)
                return subprocess.CompletedProcess(command,verify_code,b'',b'Logged in using ChatGPT')
            with patch.object(entry,'ROOT',state), patch.object(entry,'CODEX_HOME',home), \
                 patch.object(entry,'prepare_environment'),patch.object(entry,'find_codex',return_value='unit-codex'), \
                 patch.object(entry.subprocess,'Popen',side_effect=authorize) as login, \
                 patch.object(entry.subprocess,'run',side_effect=verify) as check, \
                 patch.object(sys,'argv',['project.py','login']+(['--device-auth'] if device else [])), \
                 contextlib.redirect_stdout(io.StringIO()):
                if replacement_error:
                    with patch.object(entry.os,'replace',side_effect=OSError('unit replacement error')):
                        with self.assertRaises(OSError):entry.main()
                elif failure:
                    with self.assertRaisesRegex(RuntimeError,failure):entry.main()
                else:self.assertEqual(entry.main(),login_code)
            login.assert_called_once()
            success=not login_code and not failure and not replacement_error
            if success:
                self.assertEqual(current.read_bytes(),replacement)
                if existing:
                    backups=list((home/'account-history').glob('*/auth.json'))
                    self.assertEqual(len(backups),1)
                    self.assertEqual(backups[0].read_bytes(),previous)
                for cache in caches:self.assertFalse(cache.exists())
                check.assert_called_once()
            else:
                if existing:self.assertEqual(current.read_bytes(),previous)
                else:self.assertFalse(current.exists())
                for cache in caches:self.assertEqual(cache.read_text(encoding='utf-8'),'original-cache')
            for temporary in staging:self.assertFalse(temporary.exists())

    def test_already_logged_in_still_authorizes_and_switches_after_success(self):
        self.exercise_login()

    def test_first_login_authorizes_and_installs_session(self):
        self.exercise_login(existing=False)

    def test_cancel_keeps_old_credentials_even_with_partial_new_session(self):
        self.exercise_login(login_code=1)

    def test_cancel_first_login_does_not_install_partial_session(self):
        self.exercise_login(existing=False,login_code=1)

    def test_invalid_new_auth_preserves_original(self):
        self.exercise_login(new_auth='invalid',failure='未获得有效')

    def test_missing_new_auth_preserves_original(self):
        self.exercise_login(new_auth='missing',failure='未获得有效')

    def test_failed_verification_preserves_original(self):
        self.exercise_login(verify_code=1,failure='验证未通过')

    def test_replacement_failure_retains_original_and_backup(self):
        self.exercise_login(replacement_error=True)

    def test_device_auth_also_uses_isolated_authorization(self):
        self.exercise_login(device=True)

    def test_existing_other_login_is_backed_up_without_logout(self):
        self.exercise_login(previous_mode='apikey')

    @unittest.skipUnless(os.name=='nt','Windows login script launcher')
    def test_gui_calls_shared_cmd_and_streams_login_output(self):
        from pdf_gui import TranslationWindow
        window=SimpleNamespace(busy=False,catalog_loading=False,login_in_progress=False,login_process=None,login_cancel_requested=threading.Event(),
                               events=queue.Queue(),status=Mock(),sync_model_controls=Mock())
        process=Mock()
        process.wait.return_value=0
        process.stdout.__enter__=Mock(return_value=process.stdout)
        process.stdout.__exit__=Mock(return_value=False)
        process.stdout.__iter__=Mock(return_value=iter(["LOGIN_OUTPUT\n"]))
        with patch('pdf_gui.subprocess.Popen',return_value=process) as launch, \
             patch('pdf_gui.threading.Thread') as thread:
            thread.side_effect=lambda **kw:SimpleNamespace(start=kw['target'])
            TranslationWindow.login_chatgpt(window)
        command=launch.call_args.args[0]
        options=launch.call_args.kwargs
        self.assertIn('/d /c call "%PDF2ZH_LOGIN_SCRIPT%"',command)
        self.assertEqual(options['env']['PDF2ZH_LOGIN_SCRIPT'],str(PROJECT_ROOT/'登录ChatGPT.cmd'))
        self.assertNotIn('logout',command)
        self.assertNotIn('--device-auth',command)
        self.assertEqual(options['creationflags'],subprocess.CREATE_NO_WINDOW)
        self.assertEqual(options['env']['PDF2ZH_LOGIN_FROM_GUI'],'1')
        self.assertEqual(options['stdin'],subprocess.DEVNULL)
        self.assertEqual(options['stdout'],subprocess.PIPE)
        self.assertEqual(window.events.get_nowait(),('line','LOGIN_OUTPUT'))
        self.assertEqual(window.events.get_nowait(),('login_done',0))
        self.assertIsNone(window.login_process)

    @unittest.skipUnless(os.name=='nt','Windows command execution')
    def test_real_windows_launch_with_chinese_spaces_and_exit_codes(self):
        # Real cmd.exe -> Chinese alias -> login.cmd -> PowerShell, no accounts.
        from pdf_gui import TranslationWindow
        for exit_code in (0,7,124,130):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
                project=Path(folder)/'中文 空格 项目'
                (project/'scripts').mkdir(parents=True)
                for name in ('登录ChatGPT.cmd','login.cmd'):
                    (project/name).write_bytes((PROJECT_ROOT/name).read_bytes())
                (project/'scripts/run.ps1').write_text(f"Write-Output 'LOGIN_SCRIPT_REACHED'\nexit {exit_code}\n",encoding='utf-8')
                window=SimpleNamespace(busy=False,catalog_loading=False,login_in_progress=False,login_process=None,login_cancel_requested=threading.Event(),
                                       events=queue.Queue(),status=Mock(),sync_model_controls=Mock())
                with patch('pdf_gui.PROJECT_ROOT',project), patch('pdf_gui.threading.Thread') as thread:
                    thread.side_effect=lambda **kw:SimpleNamespace(start=kw['target'])
                    TranslationWindow.login_chatgpt(window)
                events=[]
                while not window.events.empty():events.append(window.events.get_nowait())
                self.assertIn(('line','LOGIN_SCRIPT_REACHED'),events)
                self.assertIn(('login_done',exit_code),events)
                self.assertIsNone(window.login_process)

    def test_cancel_flag_ends_pending_login_without_waiting_for_timeout(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            flag=Path(folder)/'cancel';flag.touch()
            process=Mock();process.poll.return_value=None
            with patch.dict(os.environ,{'PDF2ZH_LOGIN_CANCEL_FILE':str(flag)}), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(entry.wait_for_login(process),130)
            process.terminate.assert_called_once()
            process.wait.assert_called_once_with(timeout=5)

    def test_default_login_timeout_is_exactly_five_minutes(self):
        process=Mock();process.poll.return_value=None
        with patch.object(entry,'login_cancel_requested',return_value=False), \
             patch.object(entry.time,'monotonic',side_effect=[0,299,300]), \
             patch.object(entry.time,'sleep') as sleep, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(entry.wait_for_login(process),124)
        sleep.assert_called_once_with(0.1)
        process.terminate.assert_called_once()

    def test_real_pending_process_is_stopped_on_timeout(self):
        process=subprocess.Popen([sys.executable,'-B','-c','import time; time.sleep(60)'],
                                 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            with patch.object(entry,'login_cancel_requested',return_value=False), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(entry.wait_for_login(process,timeout=0.15),124)
            self.assertIsNotNone(process.poll())
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=5)
