# -*- coding: utf-8 -*-
"""Stage 5: data_japanese.json — 일반·특례 용례에 요미가나를 삽입.

형식:
  1) 한자 뒤에 괄호로 적는다.            空港(くうこう)
  2) 오쿠리가나와 섞인 한자도 마찬가지.   哀(あわ)れむ, 出発(しゅっぱつ)する
  3) 한자·오쿠리가나 교차 시 각 한자마다. 離(はな)れ離(ばな)れ
검증: 구조 검증(괄호 위치/원문 복원) + 읽기 일치 검증(읽기 키 ⊆ 복원 읽기).
"""
# 이 파일은 **모듈이 아니라 실행 파일이다.**  본문이 최상위에 있어서 import 하는
# 순간 이 스테이지가 통째로 돈다 — 원전을 다시 읽고, 모델을 부르고(유료다), 산출물을
# 덮어쓴다.  이름이 같은 모듈을 잘못 집어 오는 것만으로 그 일이 벌어진 적이 있다.
# 조용히 도는 것보다 시끄럽게 서는 편이 낫다.
# 이 규칙은 tests/test_pipeline_entry.py 가 전 덱에 걸어 둔다.
if __name__ != "__main__":
    raise RuntimeError(
        "이 파일은 스크립트다 — import 하면 그 자리에서 실행된다. "
        "실행은 `python decks/kanji/pipeline/stage5_japanese.py`.")

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths
import ordering
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
C37F = CACHE.setdefault("gemini-3.7-flash", {}).setdefault("furigana", {})

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
    """API 호출 중단 시 cache/산출물을 잘린 JSON으로 남기지 않는다."""
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

# ---------- 문자 분류 ----------
def is_run(c):     # 요미가나를 달 한자 덩어리(반복부호 포함)
    o = ord(c)
    return (0x2E80 <= o <= 0x2EFF or 0x3400 <= o <= 0x4DBF or
            0x4E00 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or
            0x20000 <= o <= 0x2FFFF or c in "々〆")

def is_kana(c):
    o = ord(c)
    return 0x3041 <= o <= 0x309F or 0x30A1 <= o <= 0x30FA or o == 0x30FC

KT2H = str.maketrans({chr(o): chr(o - 0x60) for o in range(0x30A1, 0x30F7)})

def norm(s):
    # 카타카나->히라가나, ー 제거, 촉음 っ/ッ 은 つ/ツ 와 동일 취급(圧迫 あっぱつ ↔ アツ)
    s = s.translate(KT2H).replace("ー", "")
    return s.replace("っ", "つ").replace("ッ", "ツ")

def validate(w, ja):
    """ja 가 규칙을 준수하면 {'new': 신규읽기, 'all': 기인쇄분 포함 읽기} 를, 아니면 None.

    - 반각 (…)  : 모델이 새로 단 요미가나. 원문에는 없던 것이므로 복원 시 제거된다.
    - 전각 （…）: 공식 표 등에서 원래 인쇄된 요미가나. 원문의 일부이므로 그대로 유지해야 하며,
                  읽기 일치 판정 시에만 참고한다.
    """
    if not isinstance(ja, str) or not ja:
        return None
    word_parts, new_parts, all_parts = [], [], []
    i, n = 0, len(ja)
    while i < n:
        c = ja[i]
        if is_run(c):
            j = i
            while j < n and is_run(ja[j]):
                j += 1
            word_parts.append(ja[i:j])
            if j < n and ja[j] in ("(", "（"):
                half = ja[j] == "("
                close = ")" if half else "）"
                k = ja.find(close, j)
                if k == -1:
                    return None
                tok = ja[j:k + 1]
                inner = ja[j + 1:k]
                if not inner or not all(is_kana(ch) for ch in inner):
                    return None
                all_parts.append(inner)
                if half:
                    new_parts.append(inner)
                else:
                    word_parts.append(tok)   # 기인쇄 전각 괄호는 원문의 일부
                i = k + 1
            else:
                return None          # 모든 한자 덩어리 뒤에는 괄호가 와야 한다
        else:
            word_parts.append(c)
            if is_kana(c):
                new_parts.append(c)   # 맨바깥 오쿠리가나도 읽기의 일부
                all_parts.append(c)
            i += 1
    if "".join(word_parts) != w:
        return None                   # 괄호 추가 외의 변경 금지
    return {"new": "".join(new_parts), "all": "".join(all_parts)}

def reading_ok(concat, rdkey):
    """읽기 키(한자가 담당하는 활용 읽기일 수 있음)가 복원 읽기에 있는지."""
    return norm(rdkey.replace("ー", "")) in norm(concat)

HAS_PRE = re.compile(r"（")

# ---------- 대상 수집 ----------
data = json.load(open(paths.D4_TRANSLATE, encoding="utf-8"))
previous_annotations = {}
previous_path = paths.D5_JAPANESE
if previous_path.exists():
    with previous_path.open(encoding="utf-8") as stream:
        previous_data = json.load(stream)
    for previous_kanji, previous_record in previous_data.items():
        for bucket, context_kind in (("readings", "일반"), ("except", "특례")):
            for previous_examples in previous_record.get(bucket, {}).values():
                for previous_example in previous_examples:
                    # 이전 산출물은 후리가나를 표기 안에 싣는다.
                    annotation = previous_example.get("w", "")
                    word = ordering.plain_surface(annotation)
                    if word and validate(word, annotation) is not None:
                        context = f"{previous_kanji}의 {context_kind} 읽기"
                        previous_annotations.setdefault((word, context), set()).add(annotation)

items = {}  # (단어, 읽기키) -> {ko, contexts, exception}

def add_item(w, rd, ko, context, is_exception=False):
    item = items.setdefault(
        (w, rd), {"ko": ko or "", "contexts": [], "exception": False})
    if not item["ko"] and ko:
        item["ko"] = ko
    if context not in item["contexts"]:
        item["contexts"].append(context)
    if is_exception:
        item["exception"] = True

for kanji, v in data.items():
    for rd, ws in v["readings"].items():
        for x in ws:
            add_item(x["w"], rd, x.get("ko", ""), f"{kanji}의 일반 읽기")
    for rd, ws in v["except"].items():
        for x in ws:
            add_item(
                x["w"], rd, x.get("ko", ""), f"{kanji}의 특례 읽기",
                is_exception=True)

def cached_annotation_ok(key):
    """구조가 깨졌거나 특례 조각과 맞지 않는 캐시는 다시 조사한다."""
    w, rd = key
    parsed = validate(w, C37F.get(f"{w}|{rd}", ""))
    if parsed is None:
        return False
    return not items[key]["exception"] or reading_ok(parsed["all"], rd)

def seed_rekeyed_annotations():
    """읽기 범주 키만 바뀐 용례는 기존 검증된 요미가나를 재사용한다.

    캐시는 ``단어|읽기키`` 단위이므로 Stage 3가 활용 키를 짧게 고치면 같은
    단어·같은 표기의 annotation도 miss가 된다. 새 읽기를 실제로 포함하는 유효한
    기존 annotation이 하나로 결정될 때만 새 키에 복사한다. 우선 직전 산출물의
    같은 한자·일반/특례 context를 사용하고, 없을 때만 전역 word cache를 사용한다.
    모호하면 모델 판정에 남겨 잘못된 동음이의 읽기를 재사용하지 않는다.
    """
    by_word = {}
    for cache_key, annotation in list(C37F.items()):
        word, separator, _ = cache_key.rpartition("|")
        if not separator:
            continue
        parsed = validate(word, annotation)
        if parsed is not None:
            by_word.setdefault(word, set()).add(annotation)

    seeded = 0
    ambiguous = 0
    for word, reading in items:
        direct_key = f"{word}|{reading}"
        if cached_annotation_ok((word, reading)):
            continue
        candidates = set()
        for context in items[(word, reading)]["contexts"]:
            candidates.update(previous_annotations.get((word, context), set()))
        if len(candidates) != 1:
            global_candidates = by_word.get(word, set())
            if len(global_candidates) == 1:
                candidates = set(global_candidates)
            else:
                matching = {
                    annotation
                    for annotation in global_candidates
                    if reading_ok(validate(word, annotation)["all"], reading)
                }
                if len(matching) == 1:
                    candidates = matching
        if len(candidates) == 1:
            C37F[direct_key] = next(iter(candidates))
            seeded += 1
        elif len(candidates) > 1:
            ambiguous += 1
    if seeded:
        dump_json_atomic(CACHE_FILE, CACHE, 1)
    print(f"읽기키 변경 cache 이관: {seeded} | 모호하여 미이관: {ambiguous}")

seed_rekeyed_annotations()
todo = sorted(key for key in items if not cached_annotation_ok(key))
print(f"용례 (단어,읽기키) 쌍: {len(items)} | 캐시 히트: {len(items)-len(todo)} | 호출 대상: {len(todo)}")
if "--limit" in sys.argv:
    todo = todo[:int(sys.argv[sys.argv.index("--limit") + 1])]
    print(f"--limit 적용: {len(todo)}")

PROMPT_HEAD = (
    "너는 일본어 사전 편찬자다. 아래 일본어 단어 각각에 대해 한자 부분에 "
    "실제로 존재하는 표준 요미가나를 히라가나로 괄호 쳐서 단 문자열(\"ja\")을 만들어라.\n"
    "규칙:\n"
    "- 한자 덩어리 바로 뒤에 그 부분의 읽기를 반각 괄호 ( ) 로 적는다. 예: 空港(くうこう)\n"
    "- 오쿠리가나는 괄호 밖에 그대로 둔다. 예: 哀(あわ)れむ, 出発(しゅっぱつ)する\n"
    "- 한자와 오쿠리가나가 번갈아 나오면 각 한자 덩어리마다 괄호를 붙인다. 예: 離(はな)れ離(ばな)れ\n"
    "- 단어 안에 전각 괄호（…）요미가나가 이미 인쇄되어 있으면(예: 一人（ひとり）) 그 부분은 "
    "한 글자도 바꾸지 말고 그대로 유지하고, 요미가나 없이 남은 한자에만 반각 괄호를 붙인다.\n"
    "- yomi 는 context에 적힌 대상 한자의 읽기 참고 조각이다. 활용형은 대상 한자가 실제로 "
    "담당하는 요미카타+ー 로 축약될 수 있다. "
    "단어 전체를 표준 읽기로 표기하되, 괄호 안 읽기와 바깥 가나를 합친 전체 읽기에는 yomi 가 들어가야 한다.\n"
    "- ko 는 단어의 뜻이다. 뜻에 맞는 올바른 읽기를 고르라. 잘못된 읽기(당체독음 착오 등) 금지.\n"
    "- \"w\" 는 입력 단어를 글자 하나도 바꾸지 않고 그대로 유지한다. 괄호 삽입만 허용된다.\n"
    "- 출력은 JSON 객체 {\"results\": [{\"i\": 번호, \"w\": 단어, \"ja\": 결과}]} 하나뿐이다. 설명 금지.\n\n")

BATCH = 60

def run_batches(targets):
    """targets: [(w, rd)] -> {(w,rd): ja 또는 None}. None 은 규칙 위반(재시도 필요)."""
    out = {}
    t0 = time.time()
    for bi, group in enumerate(chunk(targets, BATCH)):
        arr_in = [{"i": i + 1, "w": w, "yomi": rd,
                   "ko": items[(w, rd)]["ko"],
                   "context": ", ".join(items[(w, rd)]["contexts"])}
                  for i, (w, rd) in enumerate(group)]
        prompt = PROMPT_HEAD + json.dumps(arr_in, ensure_ascii=False)
        try:
            resp = call_gemini(prompt)
            arr = parse_json_block(resp).get("results", [])
        except Exception as e:
            print(f"  [batch {bi}] 실패({e}) — 스킵, 재실행 시 이어감")
            continue
        got = {}
        by_idx = {it.get("i"): it for it in arr if isinstance(it, dict)}
        for j, (w, rd) in enumerate(group):
            it = by_idx.get(j + 1) or next(
                (d for d in arr if isinstance(d, dict) and d.get("w") == w), None)
            if it and it.get("ja"):
                got[(w, rd)] = str(it["ja"]).strip()
        n_ok = 0
        for key in group:
            ja = got.get(key)
            if ja:
                ja, warn = judge(key[0], key[1], ja)
                if ja is not None and warn is None:
                    out[key] = ja
                    C37F[f"{key[0]}|{key[1]}"] = ja
                    n_ok += 1
                else:
                    out[key] = None       # 구조 위반/읽기 불일치 — 재시도
            else:
                out[key] = None           # 누락/형식 오류 — 재시도
        dump_json_atomic(CACHE_FILE, CACHE, 1)
        el = time.time() - t0
        print(f"[{bi+1}] {len(group)}개 | 통과 {n_ok} | 누적 {sum(1 for v in out.values() if v)} | {el:.0f}s")
    return out

def judge(w, rd, ja):
    """(ja, warn) 반환. 규칙 위반이면 (None, None). 읽기 불일치면 warn 문자열."""
    v = validate(w, ja)
    if v is None:
        return None, None
    if reading_ok(v["all"], rd):
        return ja, None
    return ja, f"읽기키 미일치(yomi={rd}, 복원={v['all']})"

result = run_batches(todo)
fixed = {}

# ---------- 재시도: 규칙 위반분만 피드백과 함께 ----------
retry = [k for k, v in result.items() if v is None]
if retry:
    print("규칙 위반 재시도:", len(retry))
    def build_fix_prompt(group):
        arr_in = [{"i": i + 1, "w": w, "yomi": rd,
                   "ko": items[(w, rd)]["ko"],
                   "context": ", ".join(items[(w, rd)]["contexts"])}
                  for i, (w, rd) in enumerate(group)]
        return (PROMPT_HEAD
                + "이전 응답 중 아래 항목들은 규칙을 어겼다. 원인: 괄호 누락/위치 오류, "
                  "yomi 와 불일치, 단어 변경. 이번엔 반드시 규칙대로 출력하라.\n\n"
                + json.dumps(arr_in, ensure_ascii=False))
    t0 = time.time()
    for bi, group in enumerate(chunk(retry, BATCH)):
        prompt = build_fix_prompt(group)
        try:
            resp = call_gemini(prompt)
            arr = parse_json_block(resp).get("results", [])
        except Exception as e:
            print(f"  [fix {bi}] 실패({e})")
            continue
        by_idx = {it.get("i"): it for it in arr if isinstance(it, dict)}
        for j, key in enumerate(group):
            w, rd = key
            it = by_idx.get(j + 1) or next(
                (d for d in arr if isinstance(d, dict) and d.get("w") == w), None)
            if not (it and it.get("ja")):
                continue
            ja = str(it["ja"]).strip()
            ja2, warn = judge(w, rd, ja)
            if ja2 is not None:
                fixed[key] = warn or ""
                result[key] = ja2
                C37F[f"{w}|{rd}"] = ja2
        dump_json_atomic(CACHE_FILE, CACHE, 1)
        el = time.time() - t0
        print(f"[fix {bi+1}] {len(group)}개 | 복구 {len([k for k in group if k in fixed])} | {el:.0f}s")

bad = [k for k, v in result.items() if not v]

# ---------- 구제: 템플릿 채우기 (한자 덩어리마다 괄호 슬롯을 미리 만들어 제공) ----------
RUN_RE = re.compile(
    "[\u2E80-\u2EFF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF"
    "\U00020000-\U0002FFFF々〆]+")

def build_template(w):
    parts, slots, i = [], 0, 0
    for m in RUN_RE.finditer(w):
        parts.append(w[i:m.end()])
        i = m.end()
        if w[m.end():m.end() + 1] != "（":   # 기인쇄 전각 괄호가 바로 있으면 슬롯 불필요
            slots += 1
            parts.append(f"(READ{slots})")
    parts.append(w[i:])
    return "".join(parts), slots

if bad:
    print("템플릿 구제 대상:", len(bad))
    templates = {k: build_template(k[0]) for k in bad}
    rescue_ok = {}
    t0 = time.time()
    for bi, group in enumerate(chunk([k for k in bad if templates[k][1] > 0], BATCH)):
        arr_in = [{"i": n + 1, "w": w, "template": templates[(w, rd)][0],
                   "yomi": rd, "ko": items[(w, rd)]["ko"],
                   "context": ", ".join(items[(w, rd)]["contexts"])}
                  for n, (w, rd) in enumerate(group)]
        prompt = (
            "너는 일본어 사전 편찬자다. 아래 각 단어의 template 에서 (READn) 자리에만 "
            "바로 앞 한자 덩어리의 실제 표준 읽기를 히라가나로 채워 완성한 문자열(\"ja\")을 만들어라.\n"
            "규칙:\n"
            "- (READn) 자리 외에는 어떤 글자도 추가/삭제/변경하지 마라. 전각 괄호（…）는 절대 보존한다.\n"
            "- yomi 는 읽기 참고힌트(활용어간 축약 포함), ko 는 뜻이다. 이에 맞는 올바른 읽기를 쓰라.\n"
            "- 출력은 JSON 객체 {\"results\": [{\"i\": 번호, \"ja\": 완성된 문자열}]} 하나뿐이다.\n\n"
            + json.dumps(arr_in, ensure_ascii=False))
        try:
            resp = call_gemini(prompt)
            arr = parse_json_block(resp).get("results", [])
        except Exception as e:
            print(f"  [rescue {bi}] 실패({e})")
            continue
        by_idx = {it.get("i"): it for it in arr if isinstance(it, dict)}
        for j, key in enumerate(group):
            w, rd = key
            it = by_idx.get(j + 1)
            if not (it and it.get("ja")):
                continue
            ja2, warn = judge(w, rd, str(it["ja"]).strip())
            if ja2 is not None and "READ" not in ja2:
                rescue_ok[key] = warn or ""
                fixed[key] = warn or ""
                result[key] = ja2
                C37F[f"{w}|{rd}"] = ja2
        dump_json_atomic(CACHE_FILE, CACHE, 1)
        el = time.time() - t0
        print(f"[rescue {bi+1}] {len(group)}개 | 복구 {len([k for k in group if k in rescue_ok])} | {el:.0f}s")

# ---------- 결과 보고 ----------
seen_warn = set()
for (w, rd), msg in sorted({k: v for k, v in fixed.items() if v}.items()):
    if (w, rd) not in seen_warn and result.get((w, rd)):
        seen_warn.add((w, rd))
        print(f"경고(구조 통과, 읽기키 불일치 — 저장함): {w} | {rd} | {C37F.get(f'{w}|{rd}')}")
for w, rd in bad:
    if not result.get((w, rd)):
        print("요미가나 확정 실패:", w, "|", rd)

# ---------- 임베딩 ----------
n_embed = 0
n_empty = 0
n_invalid = 0
n_except = 0
n_except_mismatch = 0
for kanji, v in data.items():
    new_rd = {}
    for rd, ws in v["readings"].items():
        out = []
        for x in ws:
            ja = C37F.get(f"{x['w']}|{rd}", result.get((x["w"], rd)) or "")
            if not ja:
                n_empty += 1
            elif validate(x["w"], ja) is None:
                n_invalid += 1
            # 별도 필드가 아니라 표기 자체에 후리가나를 싣는다.
            out.append({"w": ja or x["w"], "ko": x.get("ko", "")})
        new_rd[rd] = out
    v["readings"] = new_rd
    new_except = {}
    for rd, ws in v["except"].items():
        out = []
        for x in ws:
            ja = C37F.get(f"{x['w']}|{rd}", result.get((x["w"], rd)) or "")
            if not ja:
                n_empty += 1
            else:
                parsed = validate(x["w"], ja)
                if parsed is None:
                    n_invalid += 1
                elif not reading_ok(parsed["all"], rd):
                    n_except_mismatch += 1
            out.append({"w": ja or x["w"], "ko": x.get("ko", "")})
            n_except += 1
        new_except[rd] = out
    v["except"] = new_except
    n_embed += 1

dump_json_atomic(CACHE_FILE, CACHE, 1)
if n_empty or n_invalid or n_except_mismatch:
    raise RuntimeError(
        "요미가나 정상화 실패: "
        f"공란 {n_empty}개, 구조 오류 {n_invalid}개, "
        f"특례 읽기 불일치 {n_except_mismatch}개 — 다시 실행해 cache를 보완한다")
# 용례 순서는 여기서 확정한다. 편집기 저장 경로도 같은 규칙을 쓴다.
ordering.sort_payload(data)
dump_json_atomic(paths.D5_JAPANESE, data, 2)
print(
    f"data_japanese.json written: {len(data)} | 특례 {n_except} | "
    f"후리가나 공란 {n_empty} | 구조 오류 {n_invalid} | 특례 읽기 불일치 {n_except_mismatch}")
