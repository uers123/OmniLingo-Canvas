"""腾讯云机器翻译（TMT）适配器，TC3-HMAC-SHA256 签名。

⚠️ 无审查模式下管道会自动切换至 local_llm。
依赖: pip install requests；环境变量 TENCENT_SECRET_ID / TENCENT_SECRET_KEY
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import List, Optional

from ...errors import EngineLoadError, TranslationError
from ...models import TranslateItem, Translation
from ...registry import register
from ..base import BaseTranslator

_HOST = "tmt.tencentcloudapi.com"
_SERVICE = "tmt"
_VERSION = "2018-03-21"
_REGION = "ap-guangzhou"


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _sign(secret_id: str, secret_key: str, action: str, payload: dict) -> dict:
    ts = int(time.time())
    date = time.strftime("%Y-%m-%d", time.gmtime(ts))
    ct = "application/json; charset=utf-8"
    body = json.dumps(payload, ensure_ascii=False)
    canonical_headers = f"content-type:{ct}\nhost:{_HOST}\nx-tc-action:{action.lower()}\n"
    signed_headers = "content-type;host;x-tc-action"
    canonical_request = (
        "POST\n/\n\n" + canonical_headers + "\n" + signed_headers + "\n" + _sha256_hex(body)
    )
    scope = f"{date}/{_SERVICE}/tc3_request"
    string_to_sign = (
        f"TC3-HMAC-SHA256\n{ts}\n{scope}\n" + _sha256_hex(canonical_request)
    )
    secret_date = _hmac(b"TC3" + secret_key.encode(), date)
    secret_service = _hmac(secret_date, _SERVICE)
    secret_signing = _hmac(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign, hashlib.sha256).hexdigest()
    authorization = (
        f"TC3-HMAC-SHA256 Credential={secret_id}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {
        "Authorization": authorization,
        "Content-Type": ct,
        "Host": _HOST,
        "X-TC-Action": action,
        "X-TC-Version": _VERSION,
        "X-TC-Timestamp": str(ts),
        "X-TC-Region": _REGION,
    }


@register("translate", "tencent")
class TencentTranslator(BaseTranslator):
    name = "tencent"

    def __init__(self, secret_id_env: str = "TENCENT_SECRET_ID",
                 secret_key_env: str = "TENCENT_SECRET_KEY",
                 source: str = "jp", target: str = "zh", **kwargs):
        super().__init__(**kwargs)
        self.secret_id = os.environ.get(secret_id_env, "")
        self.secret_key = os.environ.get(secret_key_env, "")
        self.source = source
        self.target = target

    def translate(self, items, context="", glossary=None, task_type="manga"):
        if not (self.secret_id and self.secret_key):
            raise EngineLoadError(
                "腾讯翻译需要设置 TENCENT_SECRET_ID 与 TENCENT_SECRET_KEY"
            )
        try:
            import requests
        except ImportError as e:
            raise EngineLoadError("需要 requests: pip install requests") from e

        texts = [i.text for i in items if i.text.strip()]
        if not texts:
            return []
        payload = {
            "SourceTextList": texts,
            "Source": self.source,
            "Target": self.target,
            "ProjectId": 0,
        }
        headers = _sign(self.secret_id, self.secret_key, "TextTranslateBatch", payload)
        try:
            resp = requests.post(
                f"https://{_HOST}/", headers=headers,
                data=json.dumps(payload, ensure_ascii=False), timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("Response", {}).get("Error"):
                raise TranslationError(
                    f"腾讯翻译错误: {data['Response']['Error'].get('Message')}"
                )
            translated = data["Response"].get("TargetTextList", [])
        except TranslationError:
            raise
        except Exception as e:
            raise TranslationError(f"腾讯翻译调用失败: {e}") from e

        out: List[Translation] = []
        ti = 0
        for item in items:
            if item.text.strip():
                out.append(Translation(
                    region_index=item.region_index,
                    source_text=item.text,
                    translated_text=translated[ti] if ti < len(translated) else "",
                    glossary_hits=glossary.lookup(item.text) if glossary else [],
                ))
                ti += 1
            else:
                out.append(Translation(
                    region_index=item.region_index, source_text=item.text,
                    translated_text="",
                ))
        return out
