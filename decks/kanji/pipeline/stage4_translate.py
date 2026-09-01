# -*- coding: utf-8 -*-
"""Stage 4: data_translate.json — 일반·특례 용례에 한국어 뜻을 삽입."""
# 이 파일은 **모듈이 아니라 실행 파일이다.**  본문이 최상위에 있어서 import 하는
# 순간 이 스테이지가 통째로 돈다 — 원전을 다시 읽고, 모델을 부르고(유료다), 산출물을
# 덮어쓴다.  이름이 같은 모듈을 잘못 집어 오는 것만으로 그 일이 벌어진 적이 있다.
# 조용히 도는 것보다 시끄럽게 서는 편이 낫다.
# 이 규칙은 tests/test_pipeline_entry.py 가 전 덱에 걸어 둔다.
if __name__ != "__main__":
    raise RuntimeError(
        "이 파일은 스크립트다 — import 하면 그 자리에서 실행된다. "
        "실행은 `python decks/kanji/pipeline/stage4_translate.py`.")

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths
import re
import json
import os
import tempfile
import time
import urllib.request
from pathlib import Path
from google.oauth2 import service_account
import google.auth.transport.requests

KEY = str(paths.GEMINI_KEY)
MODEL = "gemini-3.7-flash"
REGION = "global"
PROJECT = json.load(open(KEY))["project_id"]

CACHE_FILE = str(paths.CACHE)
CACHE = json.load(open(CACHE_FILE, encoding="utf-8"))
C37W = CACHE.setdefault("gemini-3.7-flash", {}).setdefault("word_ko", {})

creds = service_account.Credentials.from_service_account_file(
    KEY, scopes=["https://www.googleapis.com/auth/cloud-platform"])

def call_gemini(prompt, retries=4):
    for attempt in range(retries):
        creds.refresh(google.auth.transport.requests.Request())
        url = (f"https://aiplatform.googleapis.com/v1/projects/{PROJECT}"
               f"/locations/{REGION}/publishers/google/models/{MODEL}:generateContent")
        body = json.dumps({
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1,
                                 "responseMimeType": "application/json"},
        }).encode()
        try:
            req = urllib.request.Request(url, data=body, method="POST", headers={
                "Authorization": f"Bearer {creds.token}",
                "Content-Type": "application/json"})
            r = urllib.request.urlopen(req, timeout=180).read().decode()
            return json.loads(r)["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            wait = min(45, 2 ** attempt * 4)
            print(f"  retry {e} in {wait}s")
            time.sleep(wait)
    raise RuntimeError("retries exhausted")

def parse_json_block(resp):
    m = None
    for mm in re.finditer(r"\{.*\}|\[.*\]", resp, re.S):
        m = mm
    return json.loads(m.group(0).replace("```json", "").replace("```", ""))

def chunk(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

def dump_json_atomic(path, payload, indent):
    """Cache와 산출물을 중간 실패로 잘린 JSON으로 남기지 않는다."""
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

data = json.load(open(paths.D3_EXAMPLE, encoding="utf-8"))

# ---------- 고유 단어 수집 + 힌트 ----------
words = set()
hints = {}
import xlrd
sh = xlrd.open_workbook(str(paths.KOREAN_XLS)).sheet_by_name("배정한자")
hanja_re = re.compile(r"[\u2E80-\u2EFF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]+")

def clean_part(s):
    s = re.sub(r"[()\[\]（）「」]", " ", s)
    s = hanja_re.sub(" ", s)
    s = s.replace(":", "").replace(";", "").replace(",", " ")
    return re.sub(r"\s+", " ", s).strip()

def parse_hun(cell):
    res = []
    for p0 in cell.split("|"):
        p = clean_part(p0)
        if not p: continue
        if "/" in p and " " in p:
            left, _, right = p.rpartition(" ")
            for t in left.split("/"):
                t = t.strip()
                if t: res.append(f"{t} {right}".strip())
        else:
            res.append(p)
    return res

kmap = {}
for r in range(1, sh.nrows):
    hz = str(sh.cell_value(r, 2)).strip()
    hn = str(sh.cell_value(r, 3)).strip()
    if not hz or not hn: continue
    vals = parse_hun(hn)
    if not vals: continue
    for c in hz:
        lst = kmap.setdefault(c, [])
        for v in vals:
            if v not in lst: lst.append(v)

for kanji, v in data.items():
    kn_hint = ""
    kns = sorted(v.get("korean", {}).items())
    if kns:
        kn_hint = ", ".join(f"{c}={'/'.join(vals[:2])}" for c, vals in kns[:3])
    for rd, ws in v["readings"].items():
        for w in ws:
            words.add(w)
            h = []
            if kn_hint: h.append(f"한자음훈:{kn_hint}")
            h.append(f"대상한자:{kanji} 일반읽기:{rd}")
            hints.setdefault(w, set()).add((" | ".join(h)))

    # Stage 1의 except는 {특례 읽기 조각: [단어]}다. 일반 readings만
    # 수집하면 弥生처럼 특례 단어 자체에는 뜻이 끝내 붙지 않는다.
    for rd, ws in v["except"].items():
        for w in ws:
            words.add(w)
            h = []
            if kn_hint: h.append(f"한자음훈:{kn_hint}")
            h.append(f"대상한자:{kanji} 특례읽기:{rd}")
            hints.setdefault(w, set()).add((" | ".join(h)))

print("고유 용례 단어:", len(words))

# ---------- 캐시 우선 ----------
done = {w: C37W[w] for w in words if C37W.get(w)}
todo = sorted(w for w in words if w not in done)
print("캐시 히트:", len(done), "| 호출 대상:", len(todo))

# ---------- 배치 번역 ----------
BATCH = 60
t0 = time.time()
for bi, group in enumerate(chunk(todo, BATCH)):
    items = []
    for i, w in enumerate(group):
        hint = "; ".join(sorted(hints.get(w, []))[:2])
        items.append({"i": i + 1, "w": w, "hint": hint})
    prompt = (
        "너는 일본어-한국어 사전 편찬자다. 아래 일본어 단어 각각의 한국어 뜻을 사전체로 짧게 작성하라.\n"
        "규칙:\n"
        "- hint의 읽기·한자음훈은 참고 자료다. 불명확하면 가장 일반적인 뜻을 쓰라.\n"
        "- 고유명사는 '고유명사' 또는 원어 표기를 유지한다.\n"
        "- \"w\" 는 입력 단어를 그대로 복사해 넣는다(일본어 표기 유지).\n"
        "- 출력은 JSON 객체 {\"results\": [{\"i\": 입력번호, \"w\": 단어, \"ko\": 뜻}]} 하나뿐이다. 설명 금지.\n\n"
        + json.dumps(items, ensure_ascii=False))
    resp = call_gemini(prompt)
    try:
        arr = parse_json_block(resp).get("results", [])
    except Exception:
        print(f"  [batch {bi}] parse 실패 — 재시도")
        time.sleep(10)
        resp = call_gemini(prompt + "\n(다시 시도)")
        arr = parse_json_block(resp).get("results", [])
    got = {}
    for j, w in enumerate(group):
        for it in arr:
            if isinstance(it, dict) and it.get("ko"):
                # 인덱스 우선 매칭, 실패 시 문자열 매칭
                if it.get("i") == j + 1 or str(it.get("w", "")) == w:
                    got[w] = str(it["ko"]).strip().rstrip(".").strip()
    n_new = 0
    for w in group:
        ko = got.get(w) or C37W.get(w) or ""
        done[w] = ko
        if got.get(w): C37W[w] = got[w]
        if got.get(w): n_new += 1
    dump_json_atomic(CACHE_FILE, CACHE, 1)
    el = time.time() - t0
    print(f"[{bi+1}] {len(group)}개 | 신규 파싱 {n_new} | 누적 {len(done)} | {el:.0f}s")

miss = [w for w in words if not done.get(w)]
print("미번역:", len(miss), miss[:20])
if miss:
    raise RuntimeError(f"일반·특례 용례 미번역 {len(miss)}개 — 재실행해 캐시를 완성한다")

# ---------- 임베딩 ----------
n_embed = 0
for kanji, v in data.items():
    new_rd = {}
    for rd, ws in v["readings"].items():
        new_rd[rd] = [{"w": w, "ko": done.get(w, "")} for w in ws]
    v["readings"] = new_rd
    new_except = {}
    for rd, ws in v["except"].items():
        new_except[rd] = [{"w": w, "ko": done[w]} for w in ws]
    v["except"] = new_except

dump_json_atomic(paths.D4_TRANSLATE, data, 2)
print("data_translate.json written:", len(data))
