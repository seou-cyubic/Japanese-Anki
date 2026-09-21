# -*- coding: utf-8 -*-
"""Vertex AI(Gemini) 호출과 응답 캐시.

한자 덱의 스테이지 2·3·4·5 가 각각 복제해 갖고 있던 것을 한 곳으로 모았다.
문법 덱도 예문 번역에 같은 것을 쓴다.

캐시는 덱마다 ``<덱>/data/cache.json`` 에 두고 ``{모델: {용도: {키: 값}}}`` 구조를
지킨다.  용도별로 칸을 나누므로 서로 다른 작업이 키를 뺏지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Iterator

import google.auth.transport.requests
from google.oauth2 import service_account

MODEL = "gemini-3.8-flash"
REGION = "global"
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


def chunk(items: list, size: int) -> Iterator[list]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def dump_json_atomic(path, payload: Any, indent: int = 1) -> None:
    """중간 실패로 잘린 JSON 을 남기지 않는다.  써 넣고, 되읽어 검증하고, 바꿔친다."""
    target = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", prefix=f".{target.name}.",
                suffix=".tmp", dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, indent=indent)
            stream.flush()
            os.fsync(stream.fileno())
        with temporary.open(encoding="utf-8") as stream:
            json.load(stream)
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def parse_json_block(response: str) -> Any:
    """모델이 코드펜스나 군말을 붙여도 마지막 JSON 덩어리를 건져낸다."""
    found = None
    for match in re.finditer(r"\{.*\}|\[.*\]", response, re.S):
        found = match
    if found is None:
        raise ValueError(f"JSON 을 찾지 못했다: {response[:200]!r}")
    return json.loads(found.group(0).replace("```json", "").replace("```", ""))


_OPEN_FILES: dict[Path, dict] = {}


def _shared_store(path: Path) -> dict:
    """같은 파일을 여는 캐시들은 **하나의 사전을 공유해야 한다**.

    각자 사본을 들고 있으면 나중에 flush 한 쪽이 앞의 것을 통째로 덮어쓴다.
    용도가 둘 이상인 스테이지에서 한쪽 결과가 조용히 사라지는 원인이 된다.
    """
    resolved = path.resolve()
    store = _OPEN_FILES.get(resolved)
    if store is None:
        try:
            store = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            store = {}
        _OPEN_FILES[resolved] = store
    return store


class Cache:
    """``{모델: {용도: {키: 값}}}`` 디스크 캐시.  용도 하나를 dict 처럼 다룬다."""

    def __init__(self, path, purpose: str, model: str = MODEL,
                 fallback_models: Iterable[str] = ()):
        """``fallback_models`` 는 **읽기만 하는** 옛 모델 칸이다.

        모델을 바꾸면 칸이 갈리므로 새 칸만 보면 이미 받은 답을 전부 다시 묻게 된다.
        새 칸에 없는 열쇠는 옛 칸에서 찾아 주고, 쓰기는 언제나 새 칸에만 한다.
        """
        self.path = Path(path)
        self.all = _shared_store(self.path)
        self.slot = self.all.setdefault(model, {}).setdefault(purpose, {})
        self.fallbacks = [self.all.get(older, {}).get(purpose, {})
                          for older in fallback_models if older != model]
        self.revoked: set[str] = set()     # 무른 열쇠는 옛 칸에서도 찾지 않는다

    def _lookup(self, key: str) -> tuple[bool, Any]:
        if key in self.slot:
            return True, self.slot[key]
        if key in self.revoked:
            return False, None
        for older in self.fallbacks:
            if key in older:
                return True, older[key]
        return False, None

    def __contains__(self, key: str) -> bool:
        return self._lookup(key)[0]

    def __getitem__(self, key: str) -> Any:
        found, value = self._lookup(key)
        if not found:
            raise KeyError(key)
        return value

    def __setitem__(self, key: str, value: Any) -> None:
        self.slot[key] = value
        self.revoked.discard(key)

    def __delitem__(self, key: str) -> None:
        """답을 무를 수 있어야 한다.

        캐시는 '다시 묻지 않기 위한 것' 이지 '옛 답을 지키기 위한 것' 이 아니다.
        판정 규칙을 고쳤는데 그 규칙에 걸리는 옛 답이 캐시에 남아 있으면, 고침이
        데이터에 영영 닿지 못한다.  버릴 수 있어야 다시 물을 수 있다.
        """
        self.slot.pop(key, None)
        self.revoked.add(key)

    def get(self, key: str, default: Any = None) -> Any:
        found, value = self._lookup(key)
        return value if found else default

    def __len__(self) -> int:
        return len(self.slot)

    def flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        dump_json_atomic(self.path, self.all, 1)


class Gemini:
    """Vertex AI 호출기.  자격 증명은 매 호출 직전에 갱신한다."""

    def __init__(self, key_path, model: str = MODEL, region: str = REGION):
        self.key_path = str(key_path)
        self.model = model
        self.region = region
        self.project = json.loads(
            Path(self.key_path).read_text(encoding="utf-8"))["project_id"]
        self.credentials = service_account.Credentials.from_service_account_file(
            self.key_path, scopes=SCOPES)

    def __call__(self, prompt: str, retries: int = 4, temperature: float = 0.1) -> str:
        url = (f"https://aiplatform.googleapis.com/v1/projects/{self.project}"
               f"/locations/{self.region}/publishers/google/models"
               f"/{self.model}:generateContent")
        body = json.dumps({
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature,
                                 "responseMimeType": "application/json"},
        }).encode()
        last = None
        for attempt in range(retries):
            self.credentials.refresh(google.auth.transport.requests.Request())
            try:
                request = urllib.request.Request(url, data=body, method="POST", headers={
                    "Authorization": f"Bearer {self.credentials.token}",
                    "Content-Type": "application/json"})
                raw = urllib.request.urlopen(request, timeout=180).read().decode()
                return json.loads(raw)["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as error:          # noqa: BLE001 — 재시도가 목적이다
                last = error
                wait = min(45, 2 ** attempt * 4)
                print(f"  retry {error} in {wait}s", flush=True)
                time.sleep(wait)
        raise RuntimeError(f"재시도 소진: {last}")

    def json(self, prompt: str, **kwargs) -> Any:
        return parse_json_block(self(prompt, **kwargs))
