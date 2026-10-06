# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run discovery with real Windows PowerShell and controlled launcher failures."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT_ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT_ROOT/'app'))
import runtime
runtime.prepare_environment()

@unittest.skipUnless(os.name=='nt','Windows PowerShell Python discovery')
class SetupTests(unittest.TestCase):
    def probe(self, launcher=None, fallback=False, explicit=False):
        with tempfile.TemporaryDirectory(dir=runtime.ROOT/'tmp') as folder:
            root=Path(folder)
            # Batch files need the active Windows ANSI encoding, not UTF-8.
            success=f'@echo off\necho {sys.executable}\nexit /b 0\n'
            failure='@echo off\necho No suitable Python runtime found 1>&2\nexit /b 1\n'
            if launcher=='3.11':
                command='@echo off\nif "%~1"=="-3.12" (\n echo No suitable Python runtime found 1>&2\n exit /b 1\n)\n'+success
                (root/'py.cmd').write_text(command,encoding='mbcs')
            elif launcher=='missing':
                (root/'py.cmd').write_text(failure,encoding='mbcs')
            (root/'python.cmd').write_text(success if fallback else failure,encoding='mbcs')
            helper=str(PROJECT_ROOT/'scripts/python_probe.ps1').replace("'","''")
            arg=" -PythonExe '"+str(root/'python.cmd').replace("'","''")+"'" if explicit else ''
            script="$ErrorActionPreference='Stop'\n. '"+helper+"'\ntry { $found=Find-SetupPython"+arg+"; Write-Output ('FOUND='+$found); exit 0 } catch { Write-Output $_.Exception.Message; exit 42 }\n"
            script_path=root/'probe.ps1'
            script_path.write_text(script,encoding='utf-8-sig')
            environment=os.environ.copy()
            environment['PATH']=str(root)+os.pathsep+str(Path(os.environ['SystemRoot'])/'System32')
            powershell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
            return subprocess.run([str(powershell),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(script_path)],
                                  env=environment,capture_output=True,text=True,timeout=30)

    def test_missing_312_continues_to_311(self):
        result=self.probe(launcher='3.11')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('FOUND='+sys.executable,result.stdout)
        self.assertNotIn('NativeCommandError',result.stderr)

    def test_missing_launcher_runtimes_fall_back_to_python(self):
        result=self.probe(launcher='missing',fallback=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('FOUND='+sys.executable,result.stdout)

    def test_no_supported_python_has_clear_message(self):
        result=self.probe(launcher='missing')
        self.assertEqual(result.returncode,42,result.stdout+result.stderr)
        self.assertIn('Install Python 3.11 or 3.12',result.stdout)
        self.assertNotIn('NativeCommandError',result.stderr)

    def test_explicit_unavailable_python_has_clear_message(self):
        result=self.probe(explicit=True)
        self.assertEqual(result.returncode,42,result.stdout+result.stderr)
        self.assertIn('specified Python is unavailable or unsupported',result.stdout)

if __name__=='__main__':unittest.main()
