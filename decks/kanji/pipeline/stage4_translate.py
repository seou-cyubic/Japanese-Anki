# -*- coding: utf-8 -*-
"""Stage 4: data_translate.json — 일반·특례 용례에 한국어 뜻을 삽입.

**뜻은 표기가 아니라 (한자, 요미카타, 표기) 에 붙는다.**

예전에는 작업 단위가 표기 하나였다 — ``words`` 가 표기의 집합이고, 캐시 열쇠도
표기였으며, 받은 답 하나를 그 표기가 나오는 모든 요미카타에 그대로 나눠 주었다.
그래서 ``音(おと)`` 와 ``音(ね)`` 는 **구조적으로** 같은 뜻일 수밖에 없었다.  프롬프트를
아무리 고쳐도 갈릴 수 없었다 — 물어보는 자리가 애초에 하나였기 때문이다.  실제로
같은 한자 안에서 표기가 겹치는 용례군 44 개(39 자) 가 전부 같은 뜻이었고, 저장소
전체의 고유 표기 10,896 개 가운데 뜻이 둘 이상인 것은 **하나도 없었다**.

    音 おと -> 소리, 음      音 ね -> 소리, 음
    下 した -> 아래, 밑      下 しも -> 아래, 밑      下 もと -> 아래, 밑

이제 열쇠가 ``한자|요미카타|표기`` 이므로 그 셋은 서로 다른 항목이고, 힌트도 이
요미카타 하나만 실린다.  ``発音`` 처럼 여러 한자 아래 같은 낱말이 나오는 것은 요미카타가
달라 항목이 갈리지만, 그 값은 어차피 다른 한자를 설명하는 자리이므로 손해가 아니다.

**뜻의 경계는 줄바꿈 하나다.**  예전 데이터에는 쉼표와 세미콜론이 섞여 있었는데, 그
둘의 뜻을 정한 곳이 어디에도 없었다 — 이 파일의 옛 프롬프트에 구분자 이야기가 한
글자도 없었다.  그것은 규약이 아니라 모델의 그때그때의 습관이었고, 세미콜론의 절반
가까이(393 건 중 182 건)는 다른 뜻이 아니라 앞 낱말의 우리말 풀이였다
(``역내; 구역의 안``).  반대로 쉼표 쪽에는 명백히 다른 뜻이 들어 있었다
(``눈알, 안구, (비유) 주요 상품``).  그래서 그 둘을 해석하는 대신 **규약을 프롬프트에
못박아 다시 받는다** — 뜻이 다르면 배열의 원소로 나누고, 같은 뜻의 유의어·풀이는
대표 하나로 합친다.  저장할 때 원소를 줄바꿈으로 잇는다(``decks/kanji/model.py``).

받은 답이 규약을 어기면 **캐시에 넣지 않는다.**  다시 돌리면 그것만 다시 묻고, 끝까지
채워지지 않으면 마지막에 선다.  틀린 답을 캐시에 굳히는 것보다 다시 묻는 편이 싸다.
"""
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
import time
from concurrent.futures import ThreadPoolExecutor

from shared.gemini import Cache, Gemini, chunk, dump_json_atomic

BATCH = 60                 # 한 번에 묻는 용례 수
WORKERS = 4                # 동시에 띄우는 호출 수
MAX_SENSES = 3             # decks/kanji/model.py 의 계약과 같은 값이다

PROMPT = (
    "너는 일본어-한국어 사전 편찬자다. 아래 항목마다 그 낱말의 한국어 뜻을 사전체로 짧게 쓴다.\n\n"
    "한 항목은 '낱말 하나' 가 아니라 **'이 한자를 이 요미카타로 읽었을 때의 그 낱말'** 이다.\n"
    "  k    대상 한자\n"
    "  rd   그 한자가 이 낱말에서 갖는 요미카타\n"
    "  w    낱말 표기\n"
    "  hint 그 한자의 한국 훈음(참고용, 틀릴 수 있다. 불명확하면 무시하고 가장 일반적인 뜻을 쓴다)\n\n"
    "[뜻을 고르는 규칙]\n"
    "1. **rd 로 읽었을 때의 뜻만 쓴다.** 표기가 같아도 요미카타가 다르면 다른 낱말이다.\n"
    "   다른 요미카타의 뜻을 끌어오지 않는다.\n"
    "     音(おと)  귀에 들리는 물리적인 소리        音(ね)   정취가 실린 울림, 음색\n"
    "     下(した)  위치가 아래                    下(しも)  (강·신분·서열의) 아래쪽, 하류\n"
    "     下(もと)  무엇의 발치, 영향이 미치는 자리\n"
    "2. 그 요미카타 고유의 뉘앙스가 드러나게 쓴다. 두 요미카타의 뜻이 같아 보이면\n"
    "   더 좁혀 쓸 수 있는지 먼저 따진 뒤에 쓴다.\n"
    "3. 그래도 정말 같으면 같게 써도 된다. 다만 그때는 why 에 왜 같은지 적는다.\n\n"
    "[뜻을 적는 규칙 — 이것이 곧 출력 형식이다]\n"
    "4. 뜻이 여럿이면 ko 배열의 **원소로 나눈다.** 최대 %(max)d개.\n"
    "   원소를 나누는 기준은 **의미가 다른가** 하나뿐이다.\n"
    "5. **유의어·바꿔 쓴 말·풀이는 나누지 않는다.** 같은 뜻을 가리키는 여러 표현 가운데\n"
    "   **가장 대표적인 것 하나만** 남기고 나머지는 버린다.\n"
    "     '역내; 구역의 안'      -> [\"역내\"]          한자어와 그 우리말 풀이는 한 뜻이다\n"
    "     '오른쪽; 우측'         -> [\"오른쪽\"]\n"
    "     '날카롭다; 예리하다'    -> [\"날카롭다\"]\n"
    "     '더럽히다, 오염시키다'  -> [\"더럽히다\"]\n"
    "6. 의미가 다른 것은 반드시 나눈다.\n"
    "     '눈알, 안구, (비유) 주요 상품'  -> [\"눈알\", \"(비유) 주요 상품\"]\n"
    "     '담당(자), 걸이, 외상 거래'     -> [\"담당자\", \"걸이\", \"외상 거래\"]\n"
    "7. **원소 하나 안에서 쉼표(,)·세미콜론(;)·가운뎃점(·)·빗금(/)을 뜻을 가르는 구분자로\n"
    "   쓰지 않는다.** 뜻을 가르는 것은 오직 배열의 원소다.\n"
    "   문법·용법을 밝히는 괄호는 원소 안에 남겨도 된다 — \"(잔을) 비우다\", \"(비유) 주요 상품\".\n"
    "8. 고유명사는 '고유명사' 임을 밝히거나 원어 표기를 유지한다.\n\n"
    "[출력]\n"
    "{\"results\": [{\"i\": 입력번호, \"ko\": [\"뜻\", ...], \"why\": \"이 요미카타를 같은 표기의 다른\n"
    "요미카타와 가르는 한 마디. 가를 것이 없으면 빈 문자열\"}]}\n"
    "JSON 객체 하나뿐이다. 설명 금지.\n\n"
)


def top_level_semicolon(value):
    """괄호 밖의 세미콜론.  ``일위(계급의 하나; 대위)`` 의 것은 경계가 아니다."""
    depth = 0
    for character in value:
        if character in "(（[［":
            depth += 1
        elif character in ")）]］":
            depth = max(0, depth - 1)
        elif character == ";" and depth == 0:
            return True
    return False


def clean(answer):
    """모델이 낸 것을 계약대로 다듬는다.  규약을 어기면 None — 캐시에 넣지 않는다."""
    if isinstance(answer, str):
        answer = [answer]
    if not isinstance(answer, list):
        return None
    lines = []
    for piece in answer:
        text = str(piece).strip().rstrip(".").strip()
        if not text or "\n" in text or top_level_semicolon(text):
            return None
        lines.append(text)
    if not lines or len(lines) > MAX_SENSES:
        return None
    return lines


# ---------- 한국 훈음 힌트 ----------
import xlrd
sh = xlrd.open_workbook(str(paths.KOREAN_XLS)).sheet_by_name("배정한자")
hanja_re = re.compile(r"[⺀-⻿㐀-䶿一-鿿豈-﫿]+")


def clean_part(s):
    s = re.sub(r"[()\[\]（）「」]", " ", s)
    s = hanja_re.sub(" ", s)
    s = s.replace(":", "").replace(";", "").replace(",", " ")
    return re.sub(r"\s+", " ", s).strip()


def parse_hun(cell):
    res = []
    for p0 in cell.split("|"):
        p = clean_part(p0)
        if not p:
            continue
        if "/" in p and " " in p:
            left, _, right = p.rpartition(" ")
            for t in left.split("/"):
                t = t.strip()
                if t:
                    res.append(f"{t} {right}".strip())
        else:
            res.append(p)
    return res


kmap = {}
for r in range(1, sh.nrows):
    hz = str(sh.cell_value(r, 2)).strip()
    hn = str(sh.cell_value(r, 3)).strip()
    if not hz or not hn:
        continue
    vals = parse_hun(hn)
    if not vals:
        continue
    for c in hz:
        lst = kmap.setdefault(c, [])
        for v in vals:
            if v not in lst:
                lst.append(v)

# ---------- 항목 모으기 ----------
data = json.load(open(paths.D3_EXAMPLE, encoding="utf-8"))

items = {}                      # "한자|읽기|표기" -> {k, rd, w, hint}
for kanji, v in data.items():
    hint = "/".join(kmap.get(kanji, [])[:2])
    # Stage 1 의 except 는 {특례 읽기 조각: [단어]} 다.  일반 readings 만 모으면
    # 弥生 처럼 특례 단어 자체에는 뜻이 끝내 붙지 않는다.
    for bucket in ("readings", "except"):
        for rd, ws in v.get(bucket, {}).items():
            for w in ws:
                items.setdefault(f"{kanji}|{rd}|{w}", {
                    "k": kanji, "rd": rd, "w": w,
                    "hint": f"{kanji}={hint}" if hint else ""})

cache = Cache(paths.CACHE, "word_ko_v2")
todo = sorted(key for key in items if clean(
    (cache.get(key) or {}).get("ko")) is None)
print(f"용례 항목 {len(items)} | 캐시 히트 {len(items) - len(todo)}"
      f" | 호출 대상 {len(todo)} | 묶음 {-(-len(todo) // BATCH)} | 동시 {WORKERS}")

# ---------- 배치 번역 ----------
gemini = Gemini(paths.GEMINI_KEY)
groups = list(chunk(todo, BATCH))


def ask(group):
    listing = [{"i": number, "k": items[key]["k"], "rd": items[key]["rd"],
                "w": items[key]["w"], "hint": items[key]["hint"]}
               for number, key in enumerate(group, 1)]
    answer = gemini.json(PROMPT % {"max": MAX_SENSES}
                         + json.dumps(listing, ensure_ascii=False))
    rows = answer.get("results", answer if isinstance(answer, list) else [])
    return group, [row for row in rows if isinstance(row, dict)]


if groups:
    start = time.time()
    done = 0
    # 호출은 나눠 띄우되 **캐시 쓰기는 이 자리 하나뿐이다.**  받는 족족 남기므로
    # 중간에 끊겨도 이미 받은 것은 잃지 않는다.
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for group, rows in pool.map(ask, groups):
            by_number = {row.get("i"): row for row in rows}
            fresh = 0
            for number, key in enumerate(group, 1):
                row = by_number.get(number)
                if not row:
                    continue
                lines = clean(row.get("ko"))
                if lines is None:
                    continue
                cache[key] = {"ko": lines, "why": str(row.get("why", "")).strip()}
                fresh += 1
            cache.flush()
            done += len(group)
            elapsed = time.time() - start
            print(f"[{done}/{len(todo)}] 신규 {fresh} | {elapsed:.0f}s", flush=True)

missing = [key for key in items if clean((cache.get(key) or {}).get("ko")) is None]
if missing:
    print("미번역:", len(missing), missing[:20])
    raise RuntimeError(
        f"용례 미번역 {len(missing)}개 — 다시 실행해 캐시를 완성한다")

# ---------- 임베딩 ----------
for kanji, v in data.items():
    for bucket in ("readings", "except"):
        group = v.get(bucket, {})
        for rd, ws in list(group.items()):
            group[rd] = [{"w": w,
                          "ko": "\n".join(cache[f"{kanji}|{rd}|{w}"]["ko"])}
                         for w in ws]

dump_json_atomic(paths.D4_TRANSLATE, data, 2)
print("data_translate.json written:", len(data))
