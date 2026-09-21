# -*- coding: utf-8 -*-
"""Stage 3: data_example.json — 요미카타·용례 추가."""
# 이 파일은 **모듈이 아니라 실행 파일이다.**  본문이 최상위에 있어서 import 하는
# 순간 이 스테이지가 통째로 돈다 — 원전을 다시 읽고, 모델을 부르고(유료다), 산출물을
# 덮어쓴다.  이름이 같은 모듈을 잘못 집어 오는 것만으로 그 일이 벌어진 적이 있다.
# 조용히 도는 것보다 시끄럽게 서는 편이 낫다.
# 이 규칙은 tests/test_pipeline_entry.py 가 전 덱에 걸어 둔다.
if __name__ != "__main__":
    raise RuntimeError(
        "이 파일은 스크립트다 — import 하면 그 자리에서 실행된다. "
        "실행은 `python decks/kanji/pipeline/stage3_examples.py`.")

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths
from shared.furigana import to_hiragana
import fuhyo
import notes as joyo_notes
import re
import json
import gzip
import heapq
import time
import itertools
import urllib.request
import pymupdf
from collections import ChainMap, Counter
from google.oauth2 import service_account
import google.auth.transport.requests

try:
    from decks.kanji.pipeline.stage3_reading_keys import (
        is_jmdict_verb_pos,
        merge_reading_rows,
        reading_category_key,
    )
except ModuleNotFoundError:  # ``python pipeline/stage3_examples.py``
    from stage3_reading_keys import (
        is_jmdict_verb_pos,
        merge_reading_rows,
        reading_category_key,
    )


KEY = str(paths.GEMINI_KEY)
MODEL = "gemini-3.8-flash"
LEGACY_MODELS = ("gemini-3.7-flash",)   # 읽기만 하는 옛 모델 캐시 칸
REGION = "global"
PROJECT = json.load(open(KEY))["project_id"]

CACHE_FILE = str(paths.CACHE)
CACHE = json.load(open(CACHE_FILE, encoding="utf-8"))
# 모델을 바꿔도 이미 받은 용례는 다시 묻지 않는다.  ``ChainMap`` 은 앞 칸(새 모델)에만
# 쓰고, 찾을 때는 옛 모델 칸까지 본다.
C_EXAMPLE = ChainMap(CACHE.setdefault(MODEL, {}).setdefault("example_word", {}),
                     *(CACHE.get(older, {}).get("example_word", {})
                       for older in LEGACY_MODELS))

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
    m = None
    for mm in re.finditer(r"\{.*\}|\[.*\]", resp, re.S):
        m = mm
    return json.loads(m.group(0).replace("```json", "").replace("```", ""))

def chunk(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

def kat2hira(s):
    return "".join(chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c for c in s)

data = json.load(open(paths.D2_KOREAN, encoding="utf-8"))
joyo_set = {k for k, v in data.items() if v["tag"] != "h"}
hyogai_order = [k for k, v in data.items() if v["tag"] == "h"]
targets = set(hyogai_order) | {"升", "朕"}

# ================= 상용한자 본표 행 파싱 =================
doc = pymupdf.open(str(paths.JOYO_PDF))
marker_re = re.compile(r'^[ァ-ー]{1,2}－[ァ-ーぁ-ん]{1,4}$')
cjk_re = re.compile(r'[\u3400-\u9FFF\U00020000-\U0002A6DF\uF900-\uFAFF]')

def classify(x0):
    if x0 < 130: return "kanji"
    if x0 < 205: return "read"
    if x0 < 358: return "ex"
    return "note"

entries = []
for pno in range(10, 161):
    page = doc[pno]
    ymin = 153 if pno == 10 else 62
    words = [w for w in page.get_text("words") if w[1] >= ymin]
    words.sort(key=lambda w: (w[1], w[0]))
    lines = []
    for w in words:
        for L in lines:
            if abs(L["y"] - w[1]) <= 5:
                L["ws"].append(w); break
        else:
            lines.append({"y": w[1], "ws": [w]})
    cur = None
    for L in sorted(lines, key=lambda l: l["y"]):
        ws = sorted(L["ws"], key=lambda w: w[0])
        kc = [w for w in ws if classify(w[0]) == "kanji"]
        rc = [w for w in ws if classify(w[0]) == "read"]
        ec = [w for w in ws if classify(w[0]) == "ex"]
        nc = [w for w in ws if classify(w[0]) == "note"]
        kmain = None
        for w in kc:
            t = w[4].strip()
            if t in ("", "＊") or marker_re.match(t): continue
            if t.startswith("（") or t.startswith("［"): continue
            if kmain is None and w[0] < 90:
                kmain = re.sub(r"（.*?）", "", t); continue
            stripped = re.sub(r"[（）［］・\s]", "", t)
            if stripped and cjk_re.fullmatch(stripped) and w[0] < 130:
                continue
        rtext = "".join(w[4] for w in rc).strip()
        etext = "".join(w[4] for w in ec).strip()
        ntext = "".join(w[4] for w in nc).strip()
        if kmain:
            cur = {"kanji": kmain, "rows": []}
            entries.append(cur)
            if rtext or etext or ntext:
                cur["rows"].append({"reading": rtext, "ex": etext, "note": ntext})
        else:
            if rtext:
                if cur is None: continue
                cur["rows"].append({"reading": rtext, "ex": etext, "note": ntext})
            elif etext or ntext:
                if cur is not None and cur["rows"]:
                    cur["rows"][-1]["ex"] += etext
                    cur["rows"][-1]["note"] += ntext

# ---- 비고칸 흡수 ----
def split_wrapped(note):
    parts, cur_s = [], note
    while True:
        m = re.search(r"）(?=[\u3400-\u9FFF\U00020000-\U0002A6DF\uF900-\uFAFF「])", cur_s)
        if not m:
            parts.append(cur_s); break
        rest = cur_s[m.end():]
        if "（" in rest:
            parts.append(cur_s[:m.end()]); cur_s = rest
        else:
            parts.append(cur_s); break
    return [p for p in parts if p]

def clean_note(tok):
    tok = tok.strip()
    if tok.startswith("「") and tok.endswith("」"):
        tok = tok.strip("「」")
    elif tok.startswith("「"):
        tok = tok.strip("「")
    return tok.split("⇔")[0].strip()

def is_example(tok):
    if not tok or not cjk_re.search(tok): return False
    bad = [r"^⇔", r"^＊", r"^\*", r"^［", r"^]", r"参照", r"とも。", r"とも言う",
           r"とも書く", r"などは", r"は，", r"は、", r"と言う", r"^○○", r"^……", r"。$"]
    return not any(re.search(p, tok) for p in bad)

readings_map = {}
for e in entries:
    rd = {}
    for row in e["rows"]:
        key = row["reading"].replace("\u3000", "").strip()
        exs = [x.strip() for x in row["ex"].split("，") if x.strip()] if row["ex"].strip() else []
        # 備考 의 「단어（よみ）」 는 付表 상호참조(포인터)이지 용례가 아니다.
        # 예외 읽기는 fuhyo 가 付表 원문에서 직접 판정한다.
        note = fuhyo.strip_reference_tokens(row["note"]).strip()
        if note:
            if "などと使う" in note:
                exs.extend(re.findall(r"「([^」]+)」", note))
            else:
                for tok in split_wrapped(note):
                    t = clean_note(tok)
                    if is_example(t):
                        exs.extend(x.strip() for x in t.split("，") if x.strip())
        rd.setdefault(key, []).extend(exs)
    readings_map[e["kanji"]] = rd
doc.close()
print("joyo reading rows assembled:", len(readings_map))

# 실제 범주화는 JMdict의 단독 표기 근거까지 로드한 뒤 수행한다.
raw_keys = {kanji: sorted(rd) for kanji, rd in readings_map.items()}

# ================= 구 상용한자 5자 (J_19811001) =================
OLD5 = ["勺", "錘", "銑", "脹", "匁"]
doc_old = pymupdf.open(str(paths.JOYO_OLD_PDF))
old_rows = []
for pno in range(doc_old.page_count):
    page = doc_old[pno]
    words_o = page.get_text("words")
    lines_o = []
    for w in words_o:
        for L in lines_o:
            if abs(L["y"] - w[1]) <= 4:
                L["ws"].append(w); break
        else:
            lines_o.append({"y": w[1], "ws": [w]})
    for L in sorted(lines_o, key=lambda l: l["y"]):
        ws2 = sorted(L["ws"], key=lambda w: w[0])
        cell = {"kanji": "", "read": "", "ex": "", "note": ""}
        for w in ws2:
            x0 = w[0]
            c2 = "kanji" if x0 < 60 else "read" if x0 < 150 else "ex" if x0 < 290 else "note"
            cell[c2] += w[4]
        if any(cell.values()):
            cell["kanji"] = cell["kanji"].strip()
            cell["read"] = cell["read"].replace("\u3000", "").strip()
            cell["ex"] = cell["ex"].strip().strip("()（）")
            cell["note"] = cell["note"].strip("()（）").strip()
            if re.search(r"漢字|音訓|備考", cell["read"] + cell["kanji"]): continue
            old_rows.append(cell)
doc_old.close()

for t5 in OLD5:
    rd5 = {}
    for row in old_rows:
        if row["kanji"] != t5: continue
        key5 = row["read"]
        if not key5: continue
        exs5 = [x.strip() for x in row["ex"].split("，") if x.strip()]
        rd5.setdefault(key5, []).extend(exs5)
    readings_map[t5] = rd5
    raw_keys[t5] = sorted(rd5)


# ================= 공식 읽기 (H pdf) =================
doc = pymupdf.open(str(paths.HYOGAI_DATA_PDF))
h_entries = {}
for pno in range(doc.page_count):
    page = doc[pno]
    words = page.get_text("words")
    for lo, hi, rx_lo, rx_hi in ((112, 154, 155.0, 164.0), (362, 402, 403.0, 412.0)):
        nums = [w for w in words if lo <= w[0] < hi and re.fullmatch(r"\d{1,4}", w[4])]
        for nw in nums:
            no = int(nw[4]); yN = nw[1]
            cands = [w for w in words if rx_lo <= w[0] < rx_hi and -6 <= (w[1] - yN) <= 2]
            cands.sort(key=lambda w: w[0])
            raw = "".join(w[4] for w in cands)
            reading = re.sub(r"[^ァ-ヴーぁ-んー・]", "", raw)
            h_entries[no] = reading
doc.close()
hlines = open(paths.HYOGAI_TXT, encoding="utf-8").read().splitlines()
mains = [re.sub(r"\(.*?\)", "", e.strip()) for e in hlines[2].split(",") if e.strip()]
official_raw = {ch: h_entries[n] for n, ch in enumerate(mains, start=1)}
official = {c: {"key": r, "hira": kat2hira(r)} for c, r in official_raw.items() if r}

# ================= JMdict =================
needs_boundary = {
    (kanji, reading)
    for kanji, readings in readings_map.items()
    for reading, examples in readings.items()
    if reading_category_key(kanji, reading, examples)[1] == "uninflected"
}
boundary_evidence = {}
jm = {}
ent_re = re.compile(rb"<entry>.*?</entry>", re.S)
keb_re = re.compile(rb"<keb>(.*?)</keb>", re.S)
reb_re = re.compile(rb"<reb>(.*?)</reb>", re.S)
pos_re = re.compile(rb"<pos>(.*?)</pos>", re.S)
with open(paths.JMDICT, "rb") as f:
    tail = b""
    while True:
        chunk_b = f.read(1 << 22)
        if not chunk_b: break
        d2 = tail + chunk_b
        last = d2.rfind(b"</entry>")
        if last == -1: continue
        block, tail = d2[:last + 8], d2[last + 8:]
        for m in ent_re.finditer(block):
            e = m.group(0)
            kebs = [x.decode("utf-8") for x in keb_re.findall(e)]
            rebs = [x.decode("utf-8") for x in reb_re.findall(e)]
            poses = {x.decode("utf-8") for x in pos_re.findall(e)}
            if not kebs or not rebs: continue
            for kb in kebs:
                lst = jm.setdefault(kb, [])
                for rb in rebs:
                    if rb not in lst: lst.append(rb)
                # 선택적 kana 표기가 있는 명사(境い/病い/舞い/謡い)를 활용형으로
                # 오인하지 않도록 실제 동사 POS가 있는 entry만 경계 근거로 쓴다.
                if not is_jmdict_verb_pos(poses):
                    continue
                cjk_characters = [character for character in kb if cjk_re.fullmatch(character)]
                if len(cjk_characters) != 1:
                    continue
                kanji = cjk_characters[0]
                if any(
                    character != kanji and not re.fullmatch(r"[ぁ-ゖゝゞー]", character)
                    for character in kb
                ):
                    continue
                for rb in rebs:
                    reading = kat2hira(rb)
                    if (kanji, reading) in needs_boundary:
                        rows = boundary_evidence.setdefault(kanji, {}).setdefault(reading, [])
                        if kb not in rows:
                            rows.append(kb)
print("JMdict loaded")

# ================= 실제 한자 읽기별 활용 범주화 =================
# 공식표 용례에 오쿠리가나가 없는 실제 활용행만 JMdict의 ``한자+가나``
# 단독 표기를 경계 근거로 보완한다. 이 보조 표기는 출력 용례에 추가하지 않는다.
merged = {}
category_stats = Counter()
for kanji, readings in readings_map.items():
    merged[kanji] = merge_reading_rows(
        kanji, readings, category_stats, boundary_evidence.get(kanji)
    )
# ================= 付表(except) 판정 =================
# 확정된 읽기 키가 있어야 '정규 읽기'를 정의할 수 있으므로 여기서 계산한다.
fuhyo_doc = pymupdf.open(str(paths.JOYO_PDF))
fuhyo_entries = fuhyo.parse_fuhyo(fuhyo_doc)
fuhyo_doc.close()
joyo_note_rows = {e["kanji"]: e["rows"] for e in entries}
prefectures = fuhyo.parse_prefectures(joyo_note_rows)
fuhyo_entries += [(reading, [surface]) for surface, reading in prefectures.items()]
regular_readings = fuhyo.build_regular_readings(merged)
except_map = fuhyo.compute_except(fuhyo_entries, regular_readings)
print("付表:", len(fuhyo_entries), "항목 | 都道府県:", len(prefectures),
      "| except 한자:", len(except_map),
      "| 배정:", sum(len(w) for v in except_map.values() for w in v.values()))

print(
    "reading categories done:", dict(category_stats),
    "| JMdict boundary rows:",
    sum(len(rows) for values in boundary_evidence.values() for rows in values.values()),
)
print(
    "JMdict boundary applied:",
    [
        f"{kanji}|{reading}"
        for kanji, readings in readings_map.items()
        for reading, examples in readings.items()
        if boundary_evidence.get(kanji, {}).get(reading)
        and reading_category_key(kanji, reading, examples)[0]
        != reading_category_key(
            kanji,
            reading,
            [*examples, *boundary_evidence[kanji][reading]],
        )[0]
    ],
)
for t5 in OLD5:
    print(f"구한자 {t5}:", json.dumps(merged[t5], ensure_ascii=False))

# ================= 정렬 DB =================
db = {}
for c, rds in raw_keys.items():
    s = db.setdefault(c, set())
    for r in rds: s.add(kat2hira(r))
for c, rds in jm.items():
    if len(c) == 1:
        s = db.setdefault(c, set())
        for r in rds: s.add(kat2hira(r))

SOKUON_SRC = "つちくき"
def variants(cr):
    vs = {cr}
    if cr and cr[-1] in SOKUON_SRC: vs.add(cr[:-1] + "っ")
    return vs

KANJI_RE = re.compile(r"[\u3400-\u9FFF\U00020000-\U0002A6DF\uF900-\uFAFF]+")
def tokenize(s):
    toks, i = [], 0
    while i < len(s):
        if KANJI_RE.match(s, i):
            toks.append(("k", s[i])); i += 1
        else:
            j = i
            while j < len(s) and not KANJI_RE.match(s, j): j += 1
            toks.append(("w", kat2hira(s[i:j]))); i = j
    return toks

def best_residual(surface, R, max_paths=20000):
    toks = tokenize(surface)
    best = {"other": -1, "res": None}
    steps = [0]
    def minrest(idx):
        need = 0
        for kind, t in toks[idx:]:
            need += 1 if kind == "k" else len(t)
        return need
    def dfs(pi, idx, res, other):
        steps[0] += 1
        if steps[0] > max_paths: return
        if idx == len(toks):
            if pi == len(R):
                if (other > best["other"] or
                        (other == best["other"] and
                         (best["res"] is None or len(res) < len(best["res"])))):
                    best.update(other=other, res=res)
            return
        kind, t = toks[idx]
        if kind == "w":
            if R.startswith(t, pi): dfs(pi + len(t), idx + 1, res, other)
        elif any(c in targets for c in t):
            lo = pi + 1
            hi = len(R) - minrest(idx + 1)
            for end in range(lo, hi + 1): dfs(end, idx + 1, res + R[pi:end], other)
        else:
            cands = db.get(t)
            if cands is None:
                cands = set()
                for c in t: cands |= db.get(c, set())
            for cr in list(cands):
                for v in variants(cr):
                    if R.startswith(v, pi): dfs(pi + len(v), idx + 1, res, other + len(v))
    dfs(0, 0, "", 0)
    return best["res"]

# ================= BCCWJ 스캔 =================
path = str(paths.BCCWJ)
per_char = {c: [] for c in targets}
CAP = 4000
with open(path, encoding="utf-8") as f:
    header = f.readline().rstrip("\n").split("\t")
    iLemma = header.index("lemma"); iLForm = header.index("lForm"); iFreq = header.index("frequency")
    for line in f:
        parts = line.rstrip("\n").split("\t")
        lemma = parts[iLemma]
        if not lemma or not (set(lemma) & targets): continue
        try: freq = int(parts[iFreq])
        except ValueError: continue
        lform = parts[iLForm]
        for c in set(lemma) & targets:
            h = per_char[c]
            if len(h) < CAP: heapq.heappush(h, (freq, lemma, lform))
            elif freq > h[0][0]: heapq.heapreplace(h, (freq, lemma, lform))
print(f"BCCWJ scanned ({time.time():.0f})")

# ================= 조립: 상용한자 =================
result = {}
for k in data.keys():
    result[k] = dict(data[k]["readings"])   # 현재 비어있음
for k in data.keys():
    if k in merged:
        result[k] = dict(merged[k])

# 升ショウ / 朕チン
fills = {}
for char, want in (("升", "ショウ"), ("朕", "チン")):
    wr = kat2hira(want)
    cand = sorted(per_char[char], reverse=True)
    got = []
    for freq, lemma, lform in cand:
        if "・" in lemma: continue
        rlist = jm.get(lemma) or ([lform] if lform else [])
        ok = False
        for r in rlist:
            if best_residual(lemma, kat2hira(r)) == wr: ok = True; break
        if ok and lemma not in got: got.append(lemma)
        if len(got) >= 3: break
    fills[char] = got
    print(char, want, "->", got)

# ================= 조립: 표외한자 (공식 읽키 우선) =================
skip_stats = {}
for c in hyogai_order:
    off = official.get(c)
    cand = sorted(per_char[c], reverse=True)
    if off:
        buckets, stats = {}, {}
        buckets.setdefault(off["key"], [])
        skipped = 0
        for freq, lemma, lform in cand:
            if "・" in lemma: continue
            rlist = jm.get(lemma) or ([lform] if lform else [])
            hit = False
            for r in rlist:
                if best_residual(lemma, kat2hira(r)) == off["hira"]:
                    hit = True; break
            if hit:
                buckets[off["key"]].append((freq, lemma))
            else:
                skipped += 1
        skip_stats[c] = skipped
        rd = {}
        st = {}
        for res, words_l in buckets.items():
            seenl, top, bestf = set(), [], 0
            for fr, w in sorted(words_l, reverse=True):
                bestf = max(bestf, fr)
                if w not in seenl:
                    seenl.add(w); top.append(w)
                if len(top) == 3: break
            rd[res] = top; st[res] = bestf
        result[c] = {r: rd[r] for r in sorted(rd, key=lambda x: -st[x])}
    else:
        buckets, stats = {}, {}
        for freq, lemma, lform in cand:
            if "・" in lemma: continue
            res = None
            for r in (jm.get(lemma) or ([lform] if lform else [])):
                res = best_residual(lemma, kat2hira(r))
                if res is not None: break
            if res is None: continue
            buckets.setdefault(res, []).append((freq, lemma))
        rd, st = {}, {}
        for res, words_l in buckets.items():
            seenl, top, bestf = set(), [], 0
            for fr, w in sorted(words_l, reverse=True):
                bestf = max(bestf, fr)
                if w not in seenl:
                    seenl.add(w); top.append(w)
                if len(top) == 3: break
            rd[res] = top; st[res] = bestf
        result[c] = {r: rd[r] for r in sorted(rd, key=lambda x: -st[x])}

empty = [(k, r) for k in hyogai_order for r in result[k] if not result[k][r]]
print("hyogai empty readings:", len(empty))

# ================= 데이터에 반영 + 빈 용례 생성 =================
for k, rd in result.items():
    data[k]["readings"] = rd
for k in data:
    data[k]["except"] = except_map.get(k, {})

# ================= 備考 =================
# 이 칸은 지금까지 **용례를 캐는 데에만** 쓰였고 나머지는 버려졌다.  버려진 것 안에
# 표의 다른 어디에도 없는 읽기가 들어 있다 — 「観音」は，「カンノン」。 가 그것이다.
# `notes.py` 가 종류별로 갈라 주고, 모르는 모양을 만나면 그 자리에서 선다.
#
# **나온 것은 `note` 필드에만 넣는다.**  `readings`·`except` 는 건드리지 않으므로
# 備考 가 용례로 새어 들어갈 자리가 아예 없다.
note_count = Counter()
for k in data:
    got = joyo_notes.collect(k, joyo_note_rows.get(k, []))
    if not got:
        data[k].pop("note", None)
        continue
    data[k]["note"] = got
    for entry in got:
        note_count[entry["kind"]] += 1

# **備考 의 '특별한 읽기' 는 예외 읽기다.**  ``「春雨」…などは，「はるさめ」…。`` 는 그 한자를
# 정규 읽기로 읽지 않는 낱말을 짚은 것이고, 학습자에게는 付表 의 숙자훈과 다를 것이
# 없다.  그래서 ``except`` 로 옮긴다 — 열쇠는 付表 와 같이 **낱말 전체의 읽기(히라가나)** 다.
# 옮긴 것은 ``note`` 에서 뺀다.  두 곳에 같은 것을 두지 않는다는 원칙은 그대로다.
moved = 0
for k in data:
    remaining = []
    for entry in data[k].get("note", []):
        if entry["kind"] != "special_reading":
            remaining.append(entry)
            continue
        bucket = data[k]["except"].setdefault(to_hiragana(entry["reading"]), [])
        if entry["word"] not in bucket:
            bucket.append(entry["word"])
            moved += 1
        note_count["special_reading"] -= 1
    if remaining:
        data[k]["note"] = remaining
    else:
        data[k].pop("note", None)
note_count = +note_count
print("備考:", dict(note_count), "| note 를 가진 한자:",
      sum(1 for v in data.values() if v.get("note")),
      "| 예외로 옮긴 특별한 읽기:", moved)

empty_all = [(k, r) for k, v in data.items() for r, w in v["readings"].items() if not w]
print("빈 용례 읽기:", len(empty_all))
BATCH = 20
for bi, group in enumerate(chunk(empty_all, BATCH)):
    fresh = [(k, r) for k, r in group if f"{k}|{r}" not in C_EXAMPLE]
    for k, r in group:
        ck = f"{k}|{r}"
        if ck in C_EXAMPLE:
            data[k]["readings"][r] = [C_EXAMPLE[ck]]
    if fresh:
        listing = "\n".join(f"- 한자 {k} / 요미카타 {r}" for k, r in fresh)
        prompt = (
            "아래 각 항목에 대해, '일본에서 사용되는 한자 A 를 요미카타 X 로 읽는 용례 중 "
            "가장 흔히 쓰이는 것' 하나를 일본어 단어로 제시하라.\n"
            "규칙:\n"
            "- 실제 일본어 문헌에서 흔한 단어를 우선한다. 한 글자 한자 자체도 허용된다.\n"
            "- 출력은 JSON 객체 {\"results\": [{\"kanji\": A, \"yomi\": X, \"word\": 용례}]} 하나뿐이다.\n\n"
            + listing)
        resp = call_gemini(prompt)
        parsed = parse_json_block(resp)
        arr = parsed.get("results", parsed if isinstance(parsed, list) else [])
        for it in arr:
            k, y, w = it.get("kanji"), it.get("yomi"), it.get("word")
            if k and w:
                for kk2, rr in fresh:
                    if kk2 == k and rr == y:
                        data[k]["readings"][rr] = [str(w).strip()]
                        C_EXAMPLE[f"{k}|{y}"] = str(w).strip()
        json.dump(CACHE, open(CACHE_FILE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    print(f"[빈 용례 {bi+1}] 처리 {len(group)} (신규 호출 {len(fresh)})")

# ================= 표외한자: 칸을 용례의 읽기에 맞춘다 =================
# **용례가 먼저이고, 칸은 그 용례에서 한자가 실제로 읽히는 소리일 뿐이다.**
#
# 표외한자의 칸은 한자 목록(H.txt)의 음에서 오고, 용례는 코퍼스나 모델이 채운다.
# 그래서 ``鵜`` 의 テイ 칸에 ``鵜``(う), ``蕎`` 의 キョウ 칸에 ``蕎麦``(そば) 처럼 **그
# 소리로 읽히지 않는 낱말**이 들어가 있었다.  후리가나를 사전대로 달면 칸과 어긋나고,
# 칸에 맞추면 틀린 후리가나가 된다.  용례를 믿고 칸을 옮긴다.
#
#   한자의 읽기를 갈라낼 수 있으면 그 읽기의 칸으로       鵜(う) -> う · 甕棺(かめかん) -> かめ
#   갈라낼 수 없는 숙자훈이면 낱말 전체 읽기로 예외 칸에   蕎麦(そば) · 蜻蛉(とんぼ)
#
# 칸과 소리가 연탁·반탁·촉음으로만 다른 것은 같은 읽기다(``巫覡``(ふげき) 의 ブ).
# 사전에 없는 낱말은 판정할 근거가 없으므로 그대로 둔다.  상용한자의 칸은 표가 정한
# 것이므로 건드리지 않는다.  새 칸이 음독인지는 Unihan ``kJapaneseOn`` 으로 가른다 —
# 음독이면 가타카나, 아니면 히라가나 열쇠다(기존 칸과 같은 표기법).
ROMAJI = {
    "あ": "A", "い": "I", "う": "U", "え": "E", "お": "O",
    "か": "KA", "き": "KI", "く": "KU", "け": "KE", "こ": "KO",
    "さ": "SA", "し": "SHI", "す": "SU", "せ": "SE", "そ": "SO",
    "た": "TA", "ち": "CHI", "つ": "TSU", "て": "TE", "と": "TO",
    "な": "NA", "に": "NI", "ぬ": "NU", "ね": "NE", "の": "NO",
    "は": "HA", "ひ": "HI", "ふ": "FU", "へ": "HE", "ほ": "HO",
    "ま": "MA", "み": "MI", "む": "MU", "め": "ME", "も": "MO",
    "や": "YA", "ゆ": "YU", "よ": "YO",
    "ら": "RA", "り": "RI", "る": "RU", "れ": "RE", "ろ": "RO",
    "わ": "WA", "を": "WO", "ん": "N",
    "が": "GA", "ぎ": "GI", "ぐ": "GU", "げ": "GE", "ご": "GO",
    "ざ": "ZA", "じ": "JI", "ず": "ZU", "ぜ": "ZE", "ぞ": "ZO",
    "だ": "DA", "ぢ": "JI", "づ": "ZU", "で": "DE", "ど": "DO",
    "ば": "BA", "び": "BI", "ぶ": "BU", "べ": "BE", "ぼ": "BO",
    "ぱ": "PA", "ぴ": "PI", "ぷ": "PU", "ぺ": "PE", "ぽ": "PO",
}
YOON = {"ゃ": "A", "ゅ": "U", "ょ": "O"}


def romaji(hiragana):
    """Unihan ``kJapaneseOn`` 과 같은 철자.  ``きょう`` -> ``KYOU``, ``はち`` -> ``HACHI``."""
    out = []
    index = 0
    while index < len(hiragana):
        char = hiragana[index]
        following = hiragana[index + 1] if index + 1 < len(hiragana) else ""
        if char == "っ":
            out.append(romaji(following)[:1])
        elif following in YOON:
            base = ROMAJI.get(char, "")
            if base in ("SHI", "CHI", "JI"):
                out.append(base[:-1] + YOON[following])
            else:
                out.append(base[:-1] + "Y" + YOON[following])
            index += 1
        else:
            out.append(ROMAJI.get(char, ""))
        index += 1
    return "".join(out)


def to_katakana(hiragana):
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in hiragana)


japanese_on = {}
with open(paths.UNIHAN / "Unihan_Readings.txt", encoding="utf-8") as stream:
    for line in stream:
        fields = line.rstrip("\n").split("\t")
        if len(fields) == 3 and fields[1] == "kJapaneseOn":
            japanese_on[chr(int(fields[0][2:], 16))] = set(fields[2].split())

VOICE = str.maketrans("かきくけこさしすせそたちつてとはひふへほ",
                      "がぎぐげござじずぜぞだぢづでどばびぶべぼ")
HALF = str.maketrans("はひふへほ", "ぱぴぷぺぽ")
DEVOICE = str.maketrans("がぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽ",
                        "かきくけこさしすせそたちつてとはひふへほはひふへほ")


def sound_forms(reading):
    """같은 읽기로 볼 꼴들 — 그대로·연탁·반탁·촉음편."""
    plain = kat2hira(reading).replace("ー", "")
    forms = {plain}
    if plain:
        forms.add(plain[0].translate(VOICE) + plain[1:])
        forms.add(plain[0].translate(HALF) + plain[1:])
        forms.add(plain[0].translate(DEVOICE) + plain[1:])
        if plain[-1] in SOKUON_SRC:
            forms.add(plain[:-1] + "っ")
    return forms


def kanji_residual(word, kanji, reading):
    """낱말 읽기에서 ``kanji`` 가 맡는 소리.  하나로 정해지지 않으면 None.

    다른 한자는 정렬 DB 의 읽기(연탁 포함)로 맞춰야 한다.  ``kanji`` 가 두 번 이상
    나오거나 다른 한자와 소리를 나눌 수 없으면(숙자훈) None 이다.
    """
    if word.count(kanji) != 1:
        return None
    tokens = tokenize(word)
    found = set()

    def walk(position, index, residual):
        if len(found) > 1:
            return
        if index == len(tokens):
            if position == len(reading) and residual:
                found.add(residual)
            return
        kind, text = tokens[index]
        if kind == "w":
            if reading.startswith(text, position):
                walk(position + len(text), index + 1, residual)
            return
        if text == kanji:
            for end in range(position + 1, len(reading) + 1):
                walk(end, index + 1, reading[position:end])
            return
        tried = set()
        for candidate in db.get(text, ()):
            for form in variants(candidate) | sound_forms(candidate):
                # 빈 읽기는 소리를 하나도 맡지 않는다 — 蕎麦(そば) 의 麦 가 빈칸이 되면 안 된다.
                if not form or form in tried or not reading.startswith(form, position):
                    continue
                tried.add(form)
                walk(position + len(form), index + 1, residual)

    walk(0, 0, "")
    return next(iter(found)) if len(found) == 1 else None


rekeyed = []
for k in hyogai_order:
    readings = data[k]["readings"]
    for rd in list(readings):
        forms = sound_forms(rd)
        kept = []
        for w in readings[rd]:
            # 사전의 읽기 순서를 지킨다.  앞의 것이 대표 읽기다(窪地 는 くぼち, おうち 가 아니다).
            known = list(dict.fromkeys(kat2hira(r) for r in jm.get(w, [])))
            if not known:
                kept.append(w)
                continue
            # 사전 읽기 어디에든 그 소리가 들어 있으면 옮기지 않는다.  정렬 DB 에 다른
            # 한자의 읽기가 빠져 있어 소리를 못 갈랐을 뿐인 멀쩡한 용례를 지키기 위해서다.
            if any(form in reading for form in forms for reading in known):
                kept.append(w)
                continue
            residuals = [kanji_residual(w, k, r) for r in known]
            if set(residuals) & forms:
                kept.append(w)
                continue
            usable = [r for r in residuals if r]
            if usable:
                sound = usable[0]
                key = to_katakana(sound) if romaji(sound) in japanese_on.get(k, ()) else sound
                target = readings.setdefault(key, [])
                bucket = "readings"
            else:
                key = known[0]
                target = data[k]["except"].setdefault(key, [])
                bucket = "except"
            if w not in target:
                target.append(w)
            rekeyed.append((k, rd, w, bucket, key))
        readings[rd] = kept
    for rd in [r for r, ws in readings.items() if not ws]:
        del readings[rd]
    # 숙자훈 용례밖에 없던 한자는 칸이 하나도 남지 않는다(草鞋 의 鞋, 琵琶 의 琶).
    # 칸은 용례의 요미카타일 뿐이므로 그 낱말 전체의 읽기를 칸으로 삼아 되돌린다.
    if not readings:
        for key in [key for key, words in data[k]["except"].items()
                    if any(item[0] == k and item[2] in words and item[4] == key
                           for item in rekeyed)]:
            readings[key] = data[k]["except"].pop(key)
        rekeyed[:] = [(kanji, before, word, "readings" if kanji == k else bucket, after)
                      for kanji, before, word, bucket, after in rekeyed]
print("표외한자 칸 옮김:", len(rekeyed))
for kanji, before, word, bucket, after in rekeyed:
    print(f"  {kanji} {before} {word} -> {bucket} {after}")

json.dump(data, open(paths.D3_EXAMPLE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
remain = sum(1 for v in data.values() for r, w in v["readings"].items() if not w)
print("data_example.json written | 빈 용례 잔여:", remain)
