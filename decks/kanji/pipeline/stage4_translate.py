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
    "     '눈알, 안구, (비유) 주요 상품'  -> [\"눈알\", \"주요 상품\"]\n"
못박아 다시 받는다** — 뜻이 다르면 배열의 원소로 나누고, 같은 뜻의 유의어·풀이는
대표 하나로 합친다.  저장할 때 원소를 줄바꿈으로 잇는다(``decks/kanji/model.py``).

**한 번 물어서는 안 됐다 — 그래서 두 번 묻는다.**

1 패스는 뜻을 짓는다.  짓는 일이 지배적이라 같은 호출에서 "동의어를 합쳐라"·"한자음을
거르라"·"괄호를 풀어라" 를 함께 시키면 그쪽이 밀린다.  프롬프트를 조이는 것으로는
되지 않았다 — 규칙을 아홉까지 늘려 전건 11,910 을 다시 물었는데, 뜻이 여럿인 용례가
3,521 에서 3,343 으로 5% 줄었을 뿐이었다.  표본을 손으로 재 보면 남은 것의 절반쯤이
여전히 한 뜻이다(``그릇 / 용기``, ``사흘 / 3일``).

2 패스는 짓지 않는다.  **이미 나온 답을 놓고 세 가지만 본다** — 원소가 서로 다른
말인가, 한국어로 자연스러운가(``休止`` 의 뜻은 "휴지" 가 아니다), 괄호가 남았는가.
지어낼 일이 없으니 판단이 밀릴 자리도 없다.

기계로 잴 수 있는 것은 모델에게 맡기지 않는다.  괄호는 ``clean()`` 이 **거부**하므로
캐시에 굳지 않고 다음 실행이 다시 묻는다.  "두 뜻이 같은 말인가" 는 잴 수 없어서
2 패스가 필요하고, "뜻이 그 낱말의 한국 한자음 그대로인가" 는 잴 수 있어서
``pipeline/audit_meanings.py`` 가 그 자리를 정확히 세어 준다.

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
from meanings import MAX_SENSES, agree_key, clean, final_ko, review_key
import re
import json
import time
from concurrent.futures import ThreadPoolExecutor

from shared.gemini import MODEL, Cache, Gemini, chunk, dump_json_atomic

BATCH = 60                 # 한 번에 묻는 용례 수
WORKERS = 4                # 동시에 띄우는 호출 수

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
    "5-1. **원소를 둘 이상 쓰기 전에 스스로 물어라 — '이 둘을 한국어 사전에서 서로의\n"
    "   뜻풀이로 써도 되는가?' 된다면 한 뜻이다.** 다음은 전부 한 뜻이고, 자주 틀리는 자리다.\n"
    "     고유어와 한자어     '사흘, 3일'       -> [\"사흘\"]   세는 말이 다를 뿐 같은 날수다\n"
    "     같은 뜻의 두 한자어  '여성, 여자'      -> [\"여자\"]\n"
    "     같은 뜻의 두 동사    '자라다, 성장하다' -> [\"자라다\"]\n"
    "5-2. **한자를 한국 한자음으로 그대로 읽은 것은 뜻이 아니다.** 그렇게 읽은 말이\n"
    "   한국어에서 **바로 그 뜻으로 흔히 쓰일 때만** 그 말을 쓴다.\n"
    "     人口  ->  \"인구\"        한국어에서 그 뜻으로 그대로 쓰인다.  이대로 둔다\n"
    "     悪事  ->  \"나쁜 짓\"      '악사' 는 그 뜻으로 쓰이지 않는다\n"
    "     休止  ->  \"멈춤\"        '휴지' 는 한국어에서 화장실 휴지를 먼저 뜻한다\n"
    "     胃弱  ->  \"위가 약함\"\n"
    "   **한자음을 한국어 뜻과 나란히 적지 않는다.** 하나만 고른다.\n"
    "     '의미, 뜻' -> [\"의미\"]     '광음, 세월' -> [\"세월\"]\n"
    "5-3. **한국어로 읽어서 어색하면 쓰지 않는다.** 한자에서 왔든 아니든 마찬가지다.\n"
    "   스스로 물어라 — '한국 사람에게 이 낱말을 설명할 때 내가 이 말을 쓰겠는가?'\n"
    "   쓰지 않을 말이면, 그 뜻을 한국어로 다시 적는다.\n"
    "     - 한국어에 없는 말                    '역병신' -> \"불행을 몰고 오는 사람\"\n"
    "     - 있지만 다른 뜻으로 더 흔한 말        '휴지' -> \"멈춤\"\n"
    "     - 일본어 한자어를 옮기기만 한 말        '외포' -> \"두려워함\"\n"
    "6. 의미가 다른 것은 반드시 나눈다.\n"
    "     '눈알, 안구, (비유) 주요 상품'  -> [\"눈알\", \"주요 상품\"]\n"
    "     '담당(자), 걸이, 외상 거래'     -> [\"담당자\", \"걸이\", \"외상 거래\"]\n"
    "7. **원소 하나 안에서 쉼표(,)·세미콜론(;)·가운뎃점(·)·빗금(/)을 뜻을 가르는 구분자로\n"
    "   쓰지 않는다.** 뜻을 가르는 것은 오직 배열의 원소다.\n"
    "   괄호도 구분자로 쓰지 않는다 — 아래 8 을 따른다.\n"
    "8. **괄호를 쓰지 않는다.** 괄호는 뜻을 적다 만 자리다 — 읽는 쪽은 괄호 밖만 뜻으로\n"
    "   받아 들이므로, 괄호에 담긴 것은 전달되지 않는다.\n"
    "   괄호 안의 말이 **없으면 뜻이 서지 않는다면** 괄호를 풀어 한 마디로 잇는다.\n"
    "   그 정도가 아니면 괄호를 통째로 버린다.\n"
    "     '(초밥 등을) 빚다'        -> \"초밥을 빚다\"      풀어야 뜻이 선다\n"
    "     '(사정에) 어둡다'         -> \"사정에 어둡다\"\n"
    "     '(명령 등이) 내려지다'     -> \"명령이 내려지다\"\n"
    "     '에히메 (일본의 현 이름)'  -> \"일본 에히메현\"\n"
    "     '(비유) 주요 상품'        -> \"주요 상품\"        표지가 없어도 뜻이 선다\n"
    "     '담당(자)'               -> \"담당자\"\n"
    "   괄호를 풀었더니 앞 원소와 같은 말이 되면, 그것은 애초에 나눌 것이 아니었다(5-1).\n"
    "9. 고유명사는 '고유명사' 임을 밝히거나 원어 표기를 유지한다.\n\n"
    "[출력]\n"
    "{\"results\": [{\"i\": 입력번호, \"ko\": [\"뜻\", ...], \"why\": \"이 요미카타를 같은 표기의 다른\n"
    "요미카타와 가르는 한 마디. 가를 것이 없으면 빈 문자열\"}]}\n"
    "JSON 객체 하나뿐이다. 설명 금지.\n\n"
)


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

# 이름칸이 ``v3`` 인 것은 **규약을 고쳤기 때문이다.**  ``v2`` 의 답에는 나누지 말았어야
# 할 것이 나뉘어 있었다 — ``사흘 / 3일``, ``여성 / 여자``, ``악사 / 나쁜 짓`` 처럼 같은
# 말을 두 원소로 적은 것이다(위 5-1·5-2).  프롬프트만 고치면 캐시가 옛 답을 그대로
# 내주므로 고침이 데이터에 닿지 못한다.  그래서 칸을 새로 판다 — ``v2`` 는 지우지 않고
# 남겨 두어 되돌아갈 자리로 쓴다.
cache = Cache(paths.CACHE, "word_ko_v3")
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

# ---------- 감수 (2 패스) ----------
#
# **초안과 감수를 한 호출에 담지 않는다.**  1 패스는 '뜻을 지어내는' 일이 지배적이라,
# 같은 자리에서 '동의어를 합쳐라'·'한자음을 거르라' 를 함께 시키면 그쪽이 밀린다.
# 프롬프트를 조이는 것으로는 안 됐다 — 규칙을 아홉까지 늘려 전건을 다시 물었는데 뜻이
# 여럿인 용례가 3,521 에서 3,343 으로 5% 줄었을 뿐이다.
#
# 2 패스는 짓지 않는다.  **이미 나온 답을 놓고 세 가지만 본다** — 원소가 서로 다른
# 말인가, 한국어로 자연스러운가, 괄호가 남았는가.  지어낼 일이 없으니 판단이 밀릴
# 자리도 없다.
#
# 감수는 **그 초안에 대한** 답이다.  초안이 바뀌면 감수도 다시 받아야 하므로 열쇠에
# 초안을 함께 싣는다.  그러지 않으면 새 초안에 옛 감수가 붙는다.
REVIEW_BATCH = 40          # 초안이 함께 실려 1 패스보다 항목이 무겁다
REVIEW_WORKERS = 4         # 감수는 따로 조인다 — 1 패스와 부하가 다르다
# **두 패스에 다른 모델을 쓴다.**  1 패스는 11,910 건을 찍어 내는 대량 생성이라
# flash 로 충분하고, 2 패스는 판단 하나를 정확히 해야 하는 자리다.  flash 가 1 패스
# 안에서 이미 놓친 그 판단을 2 패스에서 또 flash 에게 시키면 앞뒤가 맞지 않는다.
#
# 이 Vertex 프로젝트에 열려 있는 것은 ``gemini-3.7-flash`` 와
# ``gemini-3.1-pro-preview`` 다.  ``gemini-3.1-pro`` 는 없다(404) — 이름을 줄여
# 적지 않는다.  캐시는 모델별로 칸이 갈리므로(``shared/gemini.py`` 의 ``Cache``)
# 모델을 바꾸면 그 모델의 답만 쌓이고 다른 모델의 답을 잘못 집어 오지 않는다.
REVIEW_MODEL = "gemini-3.1-pro-preview"

REVIEW_PROMPT = """너는 한국어 사전 감수자다. 아래는 일본어 낱말에 **이미 붙어 있는** 한국어 뜻이다.
새로 짓지 않는다. 고칠 곳만 고치고 나머지는 글자 그대로 되돌린다.

  k   대상 한자        rd  그 한자가 이 낱말에서 갖는 요미카타
  w   낱말 표기        ko  지금 붙어 있는 뜻 — 이것을 감수한다

[세 가지만 본다]

1. **ko 의 원소가 둘 이상이면, 그 둘이 한국어에서 정말 다른 말인가?**
   한쪽을 다른 쪽의 뜻풀이로 써도 된다면 같은 말이다. 같으면 대표 하나만 남긴다.
     ["그릇", "용기"]         -> ["그릇"]
     ["사흘", "3일"]          -> ["사흘"]
     ["자라다", "성장하다"]    -> ["자라다"]
     ["의미", "뜻"]           -> ["의미"]
     ["물바다", "침수됨"]      -> ["물바다"]
     ["또는", "혹은"]         -> ["또는"]
   정말 다르면 손대지 않는다.
     ["사다", "화를 자초하다", "높이 평가하다"]   -> 셋 다 남긴다
     ["샛별", "스타"]                          -> 둘 다 남긴다

2. **원소 하나하나가 한국어로 자연스러운가?**
   스스로 물어라 — '한국 사람에게 이 낱말을 설명할 때 내가 이 말을 쓰겠는가?'
   - 한자를 한국 한자음으로 읽기만 한 말은, 한국어에서 **바로 그 뜻으로 흔히 쓰일 때만** 둔다.
       休止 ["휴지"]    -> ["멈춤"]        '휴지' 는 한국어에서 화장실 휴지를 먼저 뜻한다
       畏怖 ["외포"]    -> ["두려워함"]     한국어에 없는 말이다
       光陰 ["광음"]    -> ["세월"]
       疫病神 ["역병신"] -> ["불행을 몰고 오는 사람"]
       人口 ["인구"]    -> ["인구"]        한국어에서 그대로 쓰이므로 그대로 둔다
       愛情 ["애정"]    -> ["애정"]
   - 한자에서 오지 않았어도 어색하면 고쳐 쓴다.

3. **괄호를 쓰지 않는다.** 괄호 안의 말이 없으면 뜻이 서지 않는 경우에는 풀어서 한 마디로
   잇고, 그 정도가 아니면 괄호째 버린다.
     ["(초밥 등을) 빚다"]   -> ["초밥을 빚다"]
     ["(사정에) 어둡다"]    -> ["사정에 어둡다"]
     ["(비유) 주요 상품"]   -> ["주요 상품"]
     ["담당(자)"]          -> ["담당자"]

[그 밖의 규약]
- 원소는 최대 %(max)d개.
- 한 원소 안에서 쉼표(,)·세미콜론(;)·가운뎃점(·)·빗금(/)을 뜻의 구분자로 쓰지 않는다.
- rd 로 읽었을 때의 뜻만 본다. 같은 표기의 다른 요미카타 뜻을 끌어오지 않는다.
- 고칠 곳이 없으면 ko 를 **글자 그대로** 되돌린다.

[출력]
{"results": [{"i": 입력번호, "ko": ["뜻", ...], "fix": "고쳤으면 왜 고쳤는지 한 마디, 안 고쳤으면 빈 문자열"}]}
JSON 객체 하나뿐이다. 설명 금지.

"""

review = Cache(paths.CACHE, "word_ko_review_v1", REVIEW_MODEL)
reviewer = Gemini(paths.GEMINI_KEY, model=REVIEW_MODEL)


def draft_of(key):
    return cache[key]["ko"]


def reviewed_of(key):
    return clean((review.get(review_key(key, draft_of(key))) or {}).get("ko"))


review_todo = sorted(key for key in items if reviewed_of(key) is None)
print(f"[감수] 대상 {len(items)} | 캐시 히트 {len(items) - len(review_todo)}"
      f" | 호출 대상 {len(review_todo)}"
      f" | 묶음 {-(-len(review_todo) // REVIEW_BATCH)} | 동시 {REVIEW_WORKERS} | 모델 {REVIEW_MODEL}")


def ask_review(group):
    listing = [{"i": number, "k": items[key]["k"], "rd": items[key]["rd"],
                "w": items[key]["w"], "ko": draft_of(key)}
               for number, key in enumerate(group, 1)]
    answer = reviewer.json(REVIEW_PROMPT % {"max": MAX_SENSES}
                           + json.dumps(listing, ensure_ascii=False))
    rows = answer.get("results", answer if isinstance(answer, list) else [])
    return group, [row for row in rows if isinstance(row, dict)]


review_groups = list(chunk(review_todo, REVIEW_BATCH))
if review_groups:
    start = time.time()
    done = 0
    changed = 0
    with ThreadPoolExecutor(max_workers=REVIEW_WORKERS) as pool:
        for group, rows in pool.map(ask_review, review_groups):
            by_number = {row.get("i"): row for row in rows}
            for number, key in enumerate(group, 1):
                row = by_number.get(number)
                if not row:
                    continue
                lines = clean(row.get("ko"))
                if lines is None:
                    continue
                if lines != draft_of(key):
                    changed += 1
                review[review_key(key, draft_of(key))] = {
                    "ko": lines, "fix": str(row.get("fix", "")).strip()}
            review.flush()
            done += len(group)
            print(f"[감수 {done}/{len(review_todo)}] 고친 것 누계 {changed}"
                  f" | {time.time() - start:.0f}s", flush=True)

# 감수를 못 받은 항목은 **초안을 쓴다.**  뜻이 아예 없는 것(위)과 달리 초안도 쓸 수
# 있는 답이므로, 그것 때문에 파이프라인 전체를 세우지는 않는다.  대신 수를 크게
# 알린다 — 다시 돌리면 그것만 다시 묻는다.
unreviewed = [key for key in items if reviewed_of(key) is None]
if unreviewed:
    print(f"!! 감수 못 받음 {len(unreviewed)} — 그 자리는 초안을 쓴다."
          f" 다시 돌리면 그것만 다시 묻는다")
    print("  ", unreviewed[:10])


# ---------- 낱말 맞추기 (3 패스) ----------
#
# 한 낱말이 여러 한자 카드에 실린다.  값이 겹치는 것은 손해가 아니지만 **어긋나는
# 것은 손해다** — 한쪽이 틀렸다는 뜻이다.  2 패스는 항목을 하나씩 보므로 한쪽만
# 고쳐 놓기도 한다: ``傾倒`` 가 ``傾`` 카드에서는 '몰두함', ``倒`` 카드에서는
# '경도' 였고(한국어 '경도' 는 다른 뜻이 먼저다), ``公私`` 가 한쪽에서는 '공사'였다.
#
# **묶어서 하나로 강제하지 않는다.**  같은 표기라도 읽기가 갈리면 다른 낱말이다
# (``明日`` 의 ミョウ=みょうにち 와 あす).  그 갈림은 후리가나를 봐야 아는데 이
# 단계에는 아직 후리가나가 없다 — '한 한자가 같은 표기를 두 번 싣는가' 로 대신
# 재 보았더니 실제 데이터에서 다섯 건(出納·憧憬·明日·蜘蛛·足跡)을 놓쳤다.
#
# 그래서 어긋난 줄들을 **한자리에 놓고 줄마다 답하게** 한다.  같은 낱말이면 통일하고
# 다른 낱말이면 그대로 둔다 — 잘못 합칠 위험이 구조적으로 없다.
AGREE_BATCH = 12           # 묶음 하나에 실리는 '표기' 수.  줄 수는 그 두세 배다

AGREE_PROMPT = """너는 한국어 사전 감수자다. 아래는 **한 표기의 낱말이 여러 한자 카드에 실린 것**이고,
카드마다 붙은 한국어 뜻이 서로 어긋나 있다. 어긋났다는 것은 어느 한쪽이 틀렸다는 뜻이다.

  g   묶음 번호 — g 가 같은 줄은 표기가 같다
  w   낱말 표기
  k   그 카드의 한자      rd  그 한자가 이 낱말에서 갖는 요미카타
  ko  그 카드에 지금 붙어 있는 뜻

[판단]
1. **먼저 rd 를 보고 같은 낱말인지 가른다.**
   - 같은 낱말이면(대개 그렇다) 뜻이 어긋날 이유가 없다. 한 묶음의 모든 줄에
     **가장 좋은 한국어 하나를 똑같이** 준다.
   - 읽기가 갈려 서로 다른 낱말이면 통일하지 않는다. 줄마다 제 뜻을 준다.
       明日  k=明 rd=ミョウ -> みょうにち     k=日 rd=あす -> あす
       이런 줄은 same 을 false 로 적고 각자의 뜻을 쓴다.
2. 통일할 때 고르는 기준은 **어느 쪽이 한국어로 더 자연스러운가** 다.
   - 한자를 한국 한자음으로 읽기만 한 말은, 한국어에서 **바로 그 뜻으로 흔히 쓰일 때만** 쓴다.
       傾倒  '몰두함' / '경도'                -> "몰두함"    '경도' 는 한국어에서 다른 뜻이 먼저다
       公私  '공적인 일과 사적인 일' / '공사'   -> "공적인 일과 사적인 일"
       休憩  '휴식' / '휴게'                  -> "휴식"
       伯仲  '우열을 가리기 힘듦' / '백중'      -> "우열을 가리기 힘듦"
   - 둘 다 자연스러우면 짧고 흔한 쪽을 쓴다.
3. 뜻이 여럿이면 배열의 원소로 나눈다. 최대 %(max)d개.
   **같은 말을 두 원소로 적지 않는다** — '그릇, 용기' 는 한 뜻이다.
4. **괄호를 쓰지 않는다.** 괄호 없이는 뜻이 서지 않으면 풀어서 한 마디로 잇고,
   그 정도가 아니면 괄호째 버린다.
5. 한 원소 안에서 쉼표·세미콜론·가운뎃점·빗금을 뜻의 구분자로 쓰지 않는다.

[출력]
{"results": [{"i": 입력번호, "ko": ["뜻", ...], "same": true 또는 false}]}
**모든 줄에 답한다.** i 는 입력의 i 를 그대로 쓴다.
same 은 '이 줄이 같은 묶음의 다른 줄들과 같은 낱말인가' 다.
JSON 객체 하나뿐이다. 설명 금지.

"""

agree = Cache(paths.CACHE, "word_ko_agree_v1", REVIEW_MODEL)


def settled_of(key):
    """맞추기에 들어가기 전의 뜻 — 감수본, 없으면 초안."""
    reviewed = reviewed_of(key)
    return reviewed if reviewed is not None else draft_of(key)


by_surface = {}
for key, item in items.items():
    by_surface.setdefault(item["w"], []).append(key)

# 두 한자 이상에 걸쳐 있고 그 뜻이 서로 어긋나는 표기만 고른다.
clashing = [sorted(keys) for _, keys in sorted(by_surface.items())
            if len({items[k]["k"] for k in keys}) > 1
            and len({tuple(settled_of(k)) for k in keys}) > 1]
agree_todo = [group for group in clashing
              if any(clean((agree.get(agree_key(k, settled_of(k))) or {}).get("ko")) is None
                     for k in group)]
print(f"[맞추기] 뜻이 어긋난 표기 {len(clashing)}군 / 용례"
      f" {sum(len(g) for g in clashing)}건 | 물을 묶음 {len(agree_todo)}군"
      f" | 호출 {-(-len(agree_todo) // AGREE_BATCH)} | 모델 {REVIEW_MODEL}")


def ask_agree(batch):
    listing = []
    number = 0
    numbering = {}
    for group_index, group in enumerate(batch, 1):
        for key in group:
            number += 1
            numbering[number] = key
            listing.append({"i": number, "g": group_index, "w": items[key]["w"],
                            "k": items[key]["k"], "rd": items[key]["rd"],
                            "ko": settled_of(key)})
    answer = reviewer.json(AGREE_PROMPT % {"max": MAX_SENSES}
                           + json.dumps(listing, ensure_ascii=False))
    rows = answer.get("results", answer if isinstance(answer, list) else [])
    return numbering, [row for row in rows if isinstance(row, dict)]


agree_batches = list(chunk(agree_todo, AGREE_BATCH))
if agree_batches:
    start = time.time()
    done = 0
    settled_count = 0
    with ThreadPoolExecutor(max_workers=REVIEW_WORKERS) as pool:
        for numbering, rows in pool.map(ask_agree, agree_batches):
            for row in rows:
                key = numbering.get(row.get("i"))
                if key is None:
                    continue
                lines = clean(row.get("ko"))
                if lines is None:
                    continue
                agree[agree_key(key, settled_of(key))] = {
                    "ko": lines, "same": bool(row.get("same", True))}
                settled_count += 1
            agree.flush()
            done += len(numbering)
            print(f"[맞추기 {done}] 답 받은 줄 {settled_count}"
                  f" | {time.time() - start:.0f}s", flush=True)

unsettled = [k for group in clashing for k in group
             if clean((agree.get(agree_key(k, settled_of(k))) or {}).get("ko")) is None]
if unsettled:
    print(f"!! 맞추기 못 받음 {len(unsettled)} — 그 자리는 감수본을 쓴다."
          f" 다시 돌리면 그것만 다시 묻는다")
    print("  ", unsettled[:10])

# ---------- 임베딩 ----------
for kanji, v in data.items():
    for bucket in ("readings", "except"):
        group = v.get(bucket, {})
        for rd, ws in list(group.items()):
            group[rd] = [
                {"w": w,
                 "ko": "\n".join(final_ko(f"{kanji}|{rd}|{w}",
                                          cache[f"{kanji}|{rd}|{w}"]["ko"],
                                          review, agree))}
                for w in ws]

dump_json_atomic(paths.D4_TRANSLATE, data, 2)
print("data_translate.json written:", len(data))
