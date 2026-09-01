# -*- coding: utf-8 -*-
"""Stage 2: data_korean.json — data.json 에 한국어 훈음 추가."""
# 이 파일은 **모듈이 아니라 실행 파일이다.**  본문이 최상위에 있어서 import 하는
# 순간 이 스테이지가 통째로 돈다 — 원전을 다시 읽고, 모델을 부르고(유료다), 산출물을
# 덮어쓴다.  이름이 같은 모듈을 잘못 집어 오는 것만으로 그 일이 벌어진 적이 있다.
# 조용히 도는 것보다 시끄럽게 서는 편이 낫다.
# 이 규칙은 tests/test_pipeline_entry.py 가 전 덱에 걸어 둔다.
if __name__ != "__main__":
    raise RuntimeError(
        "이 파일은 스크립트다 — import 하면 그 자리에서 실행된다. "
        "실행은 `python decks/kanji/pipeline/stage2_korean.py`.")

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths
import re
import json
import time
import urllib.request
from google.oauth2 import service_account
import google.auth.transport.requests

KEY = str(paths.GEMINI_KEY)
MODEL = "gemini-3.7-flash"
REGION = "global"
PROJECT = json.load(open(KEY))["project_id"]

CACHE_FILE = str(paths.CACHE)
try:
    CACHE = json.load(open(CACHE_FILE, encoding="utf-8"))
except Exception:
    CACHE = {}
C37H = CACHE.setdefault("gemini-3.7-flash", {}).setdefault("huneum", {})

creds = service_account.Credentials.from_service_account_file(
    KEY, scopes=["https://www.googleapis.com/auth/cloud-platform"])

def call_gemini(prompt, retries=4):
    for attempt in range(retries):
        creds.refresh(google.auth.transport.requests.Request())
        url = (f"https://aiplatform.googleapis.com/v1/projects/{PROJECT}"
               f"/locations/{REGION}/publishers/google/models/{MODEL}:generateContent")
        body = json.dumps({
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2},
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
    import re as _re
    m = None
    for mm in _re.finditer(r"\{.*\}|\[.*\]", resp, _re.S):
        m = mm
    return json.loads(m.group(0).replace("```json", "").replace("```", ""))

def chunk(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

# ---------- K.xls ----------
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
    seen, out = set(), []
    for x in res:
        if x not in seen:
            seen.add(x); out.append(x)
    return out

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

# ---------- 적용 ----------
data = json.load(open(paths.D1_RAW, encoding="utf-8"))
miss_self, miss_var = [], []
for k, v in data.items():
    kor = {"본": kmap.get(k, [])}
    if not kor["본"]: miss_self.append(k)
    for alt in v.get("variant", {}):
        if alt in kmap:
            kor[alt] = kmap[alt]
    v["korean"] = kor

unk = [k for k, v in data.items()
       if set(v["korean"].keys()) <= {"본"} and not v["korean"]["본"]]
print("훈음 불명:", len(unk))

# ---------- Gemini 보강 ----------
BATCH = 25
for bi, group in enumerate(chunk(unk, BATCH)):
    fresh = [c for c in group if c not in C37H]
    for c in group:
        if c in C37H and c in data and not data[c]["korean"]["본"]:
            data[c]["korean"]["본"] = [C37H[c]]
            data[c]["korean_src"] = "gemini"
    fresh = [c for c in fresh if not data[c]["korean"]["본"]]
    if fresh:
        listing = "\n".join(f"- {c}" for c in fresh)
        prompt = (
            "아래는 '일본어에서 사용되는 한자' 목록이다. 각 한자의 한국어 훈음(훈+음)을 작성하라.\n"
            "규칙:\n"
            "- 한국 한자음 관례에 맞는 음과, 일본어에서의 용법에 기반한 훈을 '훈 음' 형식으로 쓴다"
            " (예: '벙어리 아').\n"
            "- 일본 국자 등 한국어 훈을 만들 수 없으면 훈을 생략하고 음만 쓴다 (예: '문').\n"
            "- 출력은 JSON 객체 {\"results\": [{\"char\": 한자, \"ko\": \"훈 음\"}]} 하나뿐이다.\n\n"
            + listing)
        resp = call_gemini(prompt)
        parsed = parse_json_block(resp)
        arr = parsed.get("results", parsed if isinstance(parsed, list) else [])
        for it in arr:
            if it.get("char") and it.get("ko"):
                ko = str(it["ko"]).strip()
                C37H[it["char"]] = ko
                if it["char"] in data and not data[it["char"]]["korean"]["본"]:
                    data[it["char"]]["korean"]["본"] = [ko]
                    data[it["char"]]["korean_src"] = "gemini"
        json.dump(CACHE, open(CACHE_FILE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    print(f"[훈음 {bi+1}] 처리 {len(group)}")

json.dump(data, open(paths.D2_KOREAN, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
remain = [k for k, v in data.items()
          if set(v["korean"].keys()) <= {"본"} and not v["korean"]["본"]]
print("data_korean.json written:", len(data), "| 훈음 잔여 불명:", len(remain))
