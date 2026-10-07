# SPDX-License-Identifier: AGPL-3.0-or-later
"""Download pinned PDF models once, validate SHA3-256, and reuse local assets."""
import hashlib
from pathlib import Path
import uuid
import httpx
from runtime import ROOT


def file_sha3(path):
    digest=hashlib.sha3_256()
    with Path(path).open('rb') as file:
        for chunk in iter(lambda:file.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def ensure_model(name,filename,expected_hash,urls,client,cache_dir=None):
    directory=Path(cache_dir or ROOT/'cache/babeldoc/models')
    directory.mkdir(parents=True,exist_ok=True)
    target=directory/filename
    if target.is_file() and file_sha3(target)==expected_hash:
        return {'model':name,'path':str(target),'bytes':target.stat().st_size,'cached':True}
    errors=[]
    upstreams=[key for key in ('huggingface','modelscope','hf-mirror','github') if key in urls]
    upstreams.extend(key for key in urls if key not in upstreams)
    for upstream in upstreams:
        temporary=directory/(filename+'.'+uuid.uuid4().hex+'.part')
        try:
            print('正在下载 PDF 模型：'+name+'（'+upstream+'）',flush=True)
            digest=hashlib.sha3_256()
            with client.stream('GET',urls[upstream]) as response:
                response.raise_for_status()
                with temporary.open('wb') as file:
                    for chunk in response.iter_bytes(chunk_size=1024*512):
                        digest.update(chunk);file.write(chunk)
            if digest.hexdigest()!=expected_hash:
                raise ValueError('模型 SHA3-256 校验失败')
            temporary.replace(target)
            return {'model':name,'path':str(target),'bytes':target.stat().st_size,'cached':False,'upstream':upstream}
        except (httpx.HTTPError,ValueError,OSError) as exc:
            errors.append(upstream+': '+str(exc))
            print('模型下载或校验失败，尝试下一个下载源：'+upstream,flush=True)
        finally:temporary.unlink(missing_ok=True)
    raise RuntimeError('PDF 模型准备失败：'+name+'；'+'；'.join(errors))


def preload_models():
    from babeldoc.assets.embedding_assets_metadata import (
        DOC_LAYOUT_ONNX_MODEL_URL, DOCLAYOUT_YOLO_DOCSTRUCTBENCH_IMGSZ1024ONNX_SHA3_256,
        TABLE_DETECTION_RAPIDOCR_MODEL_URL, TABLE_DETECTION_RAPIDOCR_MODEL_SHA3_256,
    )
    specs=[('DocLayout','doclayout_yolo_docstructbench_imgsz1024.onnx',
            DOCLAYOUT_YOLO_DOCSTRUCTBENCH_IMGSZ1024ONNX_SHA3_256,DOC_LAYOUT_ONNX_MODEL_URL),
           ('RapidOCR','ch_PP-OCRv4_det_infer.onnx',TABLE_DETECTION_RAPIDOCR_MODEL_SHA3_256,TABLE_DETECTION_RAPIDOCR_MODEL_URL)]
    results=[]
    with httpx.Client(follow_redirects=True,timeout=httpx.Timeout(60,connect=15)) as client:
        for spec in specs:
            result=ensure_model(*spec,client)
            results.append(result)
            if not result['cached']:
                print('PDF 模型已缓存并通过校验：'+result['model'],flush=True)
    return results
