# SPDX-License-Identifier: AGPL-3.0-or-later
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
import httpx

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import runtime
runtime.prepare_environment()
from model_assets import ensure_model


class ModelAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=runtime.ROOT/'tmp')
        self.folder=Path(self.temp.name)
        self.content=b'verified model fixture'
        self.digest=hashlib.sha3_256(self.content).hexdigest()
    def tearDown(self):self.temp.cleanup()

    def test_valid_cache_avoids_all_network_requests(self):
        (self.folder/'model.onnx').write_bytes(self.content)
        def request(req):raise AssertionError('valid cache must not access the network')
        with httpx.Client(transport=httpx.MockTransport(request)) as client:
            result=ensure_model('Unit','model.onnx',self.digest,{'huggingface':'https://fixture.invalid/model'},client,self.folder)
        self.assertTrue(result['cached'])
        self.assertEqual(result['bytes'],len(self.content))

    def test_failed_upstream_falls_back_and_installs_only_verified_model(self):
        calls=[]
        def request(req):
            calls.append(req.url.host)
            if req.url.host=='first.invalid':return httpx.Response(500)
            if req.url.host=='second.invalid':return httpx.Response(200,content=b'wrong model')
            return httpx.Response(200,content=self.content)
        urls={'huggingface':'https://first.invalid/model','modelscope':'https://second.invalid/model','hf-mirror':'https://third.invalid/model'}
        with httpx.Client(transport=httpx.MockTransport(request)) as client:
            result=ensure_model('Unit','model.onnx',self.digest,urls,client,self.folder)
        self.assertEqual(calls,['first.invalid','second.invalid','third.invalid'])
        self.assertFalse(result['cached'])
        self.assertEqual((self.folder/'model.onnx').read_bytes(),self.content)
        self.assertFalse(list(self.folder.glob('*.part')))

    def test_exhausted_or_corrupt_download_does_not_replace_existing_file(self):
        target=self.folder/'model.onnx';target.write_bytes(b'existing unverified file')
        with httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,content=b'corrupt model'))) as client:
            with self.assertRaises(RuntimeError):
                ensure_model('Unit','model.onnx',self.digest,{'huggingface':'https://fixture.invalid/model'},client,self.folder)
        self.assertEqual(target.read_bytes(),b'existing unverified file')
        self.assertFalse(list(self.folder.glob('*.part')))


if __name__=='__main__':unittest.main()
