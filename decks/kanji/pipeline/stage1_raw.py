# -*- coding: utf-8 -*-
"""Stage 1: data.json — 한자 raw 데이터 (tag / variant / except / 빈 readings)."""
# 이 파일은 **모듈이 아니라 실행 파일이다.**  본문이 최상위에 있어서 import 하는
# 순간 이 스테이지가 통째로 돈다 — 원전을 다시 읽고, 모델을 부르고(유료다), 산출물을
# 덮어쓴다.  이름이 같은 모듈을 잘못 집어 오는 것만으로 그 일이 벌어진 적이 있다.
# 조용히 도는 것보다 시끄럽게 서는 편이 낫다.
# 이 규칙은 tests/test_pipeline_entry.py 가 전 덱에 걸어 둔다.
if __name__ != "__main__":
    raise RuntimeError(
        "이 파일은 스크립트다 — import 하면 그 자리에서 실행된다. "
        "실행은 `python decks/kanji/pipeline/stage1_raw.py`.")

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths
import re
import json
import pymupdf



# ================= 상용한자 본표 스캔 =================
doc = pymupdf.open(str(paths.JOYO_PDF))
marker_re = re.compile(r'^[ァ-ー]{1,2}－[ァ-ーぁ-ん]{1,4}$')
cjk_re = re.compile(r'[\u3400-\u9FFF\U00020000-\U0002A6DF\uF900-\uFAFF]')

def classify(x0):
    if x0 < 130: return "kanji"
    if x0 < 205: return "read"
    if x0 < 358: return "ex"
    return "note"

entries = []          # {kanji, old(미사용), rows:[{reading, ex, note}]}
variants = {}         # kanji -> {variant: label}
note_log_count = 0

for pno in range(10, 161):
    page = doc[pno]
    ymin = 153 if pno == 10 else 62
    words = [w for w in page.get_text("words") if w[1] >= ymin]
    words.sort(key=lambda w: (w[1], w[0]))
    lines = []
    for w in words:
        for L in lines:
            if abs(L["y"] - w[1]) <= 5:
                L["words"].append(w); break
        else:
            lines.append({"y": w[1], "words": [w]})
    cur = None
    for L in sorted(lines, key=lambda l: l["y"]):
        ws = sorted(L["words"], key=lambda w: w[0])
        kc = [w for w in ws if classify(w[0]) == "kanji"]
        rc = [w for w in ws if classify(w[0]) == "read"]
        ec = [w for w in ws if classify(w[0]) == "ex"]
        nc = [w for w in ws if classify(w[0]) == "note"]

        kmain = None
        kvars = []           # (text, kind)
        for w in kc:
            t = w[4].strip()
            if t in ("", "＊") or marker_re.match(t):
                continue
            if t.startswith("（"):
                kvars.append((t, "paren")); continue
            if t.startswith("［"):
                kvar_words_app = (t, "bracket")
                kvars.append((t, "bracket")); continue
            if kmain is None and w[0] < 90:
                m2 = re.search(r"（([^（）]*)）", t)
                if m2 and m2.group(1).strip():
                    kvars.insert(0, (f"（{m2.group(1)}）", "paren"))
                kmain = re.sub(r"（.*?）", "", t); continue
            stripped = re.sub(r"[（）［］・\s]", "", t)
            if stripped and cjk_re.fullmatch(stripped) and w[0] < 130:
                kvars.append((t, "bare"))

        rtext = "".join(w[4] for w in rc).strip()
        etext = "".join(w[4] for w in ec).strip()
        ntext = "".join(w[4] for w in nc).strip()

        if kmain:
            cur = {"kanji": kmain, "rows": []}
            entries.append(cur)
            variants.setdefault(kmain, {})
            for t, kind in kvars:
                content = t.strip("（）［］ ")
                broken = (kind == "paren" and t.count("（") and not t.count("）"))
                label = {"paren": "康熙字典体", "bracket": "許容字体", "bare": "康熙字典体"}[kind]
                parts = [p for p in re.split(r"[・、]", content) if p]
                if not parts or broken:
                    if kind == "paren" and kmain == "亀":
                        variants[kmain]["龜"] = label
                    continue
                for p in parts:
                    p = p.strip()
                    if cjk_re.fullmatch(p):
                        variants[kmain][p] = label
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

# ---- 비고칸 -> 용례 흡수는 Stage 3 에서 수행. 여기서는 행 원문을 보존한다.
joyo_rows = {e["kanji"]: e["rows"] for e in entries}
doc.close()

joyo_list = [e["kanji"] for e in entries]
joyo_set = set(joyo_list)
assert len(joyo_set) == 2136, len(joyo_set)

json.dump({"list": joyo_list, "rows": joyo_rows,
           "variants": variants},
          open(paths.S1_JOYO, "w", encoding="utf-8"), ensure_ascii=False)

# 付表(except) 는 확정된 읽기 키가 있어야 판정할 수 있으므로 Stage 3 에서
# 계산한다.  여기서는 빈 채로 둔다.  pipeline/fuhyo.py 참조.

# ================= 태그 =================
slines = [l for l in open(paths.SCHOOL_TXT, encoding="utf-8").read().splitlines() if l.strip()]
tag_of = {}
i = 0
while i < len(slines):
    m = re.match(r"^(\d)학년$", slines[i])
    if m:
        g = m.group(1)
        declared = int(re.search(r"\((\d+)자\)", slines[i+1]).group(1))
        ks = slines[i+2].split()
        assert len(ks) == declared
        for k in ks: tag_of[k] = f"s{g}"
        i += 3
    else:
        i += 1
assert len(tag_of) == 1026 and set(tag_of) <= joyo_set

# ================= 표외한자 목록/변자 =================
hlines = open(paths.HYOGAI_TXT, encoding="utf-8").read().splitlines()
extras5 = [k.strip() for k in hlines[0].split(",") if k.strip()]
raw_main = [x.strip() for x in hlines[2].split(",") if x.strip()]
hyogai_order, seen = [], set()
hyo_variants = {}
hyo_pairs = set()
for e in extras5 + raw_main:
    m = re.match(r"^([^\(]+)(?:\((.+)\))?$", e)
    k, alt = m.group(1).strip(), m.group(2)
    if k in joyo_set or k in seen: continue
    seen.add(k); hyogai_order.append(k)
    if alt:
        hyo_variants[k] = {alt: "簡易慣用字体"}
        hyo_pairs.add((k, alt))
assert len(hyogai_order) == 876

for K, d in variants.items():
    for P in list(d):
        if (P, K) in hyo_pairs:
            d[P] = "印刷標準字体（表外漢字字体表）"

# ================= 구 5자 앵커 =================
OLD5 = ["勺", "錘", "銑", "脹", "匁"]
ANCHOR = {"勺": "釈", "錘": "粋", "銑": "線", "脹": "朝", "匁": "聞"}

# ================= 조립 =================
data = {}
for e in entries:
    k = e["kanji"]
    data[k] = {"tag": tag_of.get(k, "j"), "variant": variants.get(k, {}),
               "except": {}, "readings": {}}
keys = list(data.keys())
for t in OLD5:
    idx = keys.index(ANCHOR[t]) + 1
    items = list(data.items())
    items.insert(idx, (t, {"tag": "j", "variant": {}, "except": {}, "readings": {}}))
    data = dict(items)
    keys = list(data.keys())

for k in hyogai_order:
    if k in OLD5:
        continue    # 구 상용한자 5자는 상용한자(j) 로 이미 추가됨
    v = variants.get(k, {})
    hv = {}
    for e in extras5 + raw_main:
        m = re.match(r"^([^\(]+)(?:\((.+)\))?$", e)
        kk, alt = m.group(1).strip(), m.group(2)
        if kk == k and alt:
            hv[alt] = "簡易慣用字体"
    data[k] = {"tag": "h", "variant": hv, "except": {}, "readings": {}}

from collections import Counter
tags = Counter(v["tag"] for v in data.values())
print("total:", len(data), dict(sorted(tags.items())))
assert len(data) == 2141 + 871
assert sum(tags[f"s{i}"] for i in range(1, 7)) == 1026
assert tags["j"] == 1110 + 5 and tags["h"] == 871

json.dump(data, open(paths.D1_RAW, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("data.json written:", len(data))
