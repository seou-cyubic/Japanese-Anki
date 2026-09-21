# -*- coding: utf-8 -*-
"""Stage 1: bunpo.json — B.pdf 에서 표현 문형을 뽑는다.

원전은 『日本語表現文型辞典』(ALC).  본문의 모든 요소가 **글꼴과 크기로 구분**되므로
좌표만으로 정확히 갈라낼 수 있다.

  17.0pt  MidashiGoPro-MB31    표제형          <- 항목의 시작
  10.6pt  MidashiGoPro-MB31    상호참조 색인   (표제형이 아니다)
  14.2pt  RyuminPro-Medium     【 】 괄호
   7.6pt  RyuminPro-Medium     일본어 뜻풀이 (루비 3.9pt)
   5.7pt  RyuminPro-*          영 ／ 중 ／ 한 뜻
   5.7pt  GothicMB101Pro-Bold  급수 (「1」+「級」)
   9.2pt  RyuminPro-Bold/Medium 예문       (루비 4.6 / 3.8pt)
   9.2pt  FutoGoB101Pro-Bold   접속형
   8.9pt  RyuminPro-Regular    일본어 해설
   7.1pt  RyuminPro-Regular    영어 해설
   6.4pt  AdobeSongStd         중국어 해설
   6.4pt  AdobeMyungjoStd      한국어 해설

후리가나는 **이미 인쇄되어 있다**.  본문보다 작은 같은 글꼴이 위쪽에 놓이므로,
문자 단위 좌표로 어느 글자에 걸리는지 정확히 맞출 수 있다.  생성할 필요가 없다.
"""
import json
import re
import sys

import pymupdf

sys.path.insert(0, __file__.rsplit("pipeline", 1)[0] + "pipeline")
import paths  # noqa: E402

FIRST_PAGE = 22                      # あ行 시작
HEAD_SIZE = 17.0
HEAD_FONT = "MidashiGoPro"
BODY_SIZE = 9.2
CONNECT_FONT = "FutoGoB101Pro"
GLOSS_FONT = "RyuminPro-Medium"
LEVEL_FONT = "GothicMB101Pro"
SIDE_TAB_X = 380.0                   # 오른쪽 색인 탭은 본문이 아니다
RUBY_MAX = 5.5                       # 이보다 작은 본문 글꼴은 루비다
RUBY_RISE = 9.0                      # 루비는 본문보다 이만큼 위에 놓인다

# --- 예문의 글꼴 ---
# 예문은 9.2pt RyuminPro 로 조판되지만 **굵기가 한 가지가 아니다.**  대부분은
# Bold 이고, 9 쪽에서만 Medium 으로 조판되어 있다(43·79·80·91·145·178·199·40·337).
# 굵기 하나만 보면 그 쪽의 예문이 문장 도중에 잘리거나(``10月になりました`` 에서
# ``が、毎日暑い日が…`` 가 사라진다) 통째로 없어진다(``が`` 항목의 ②).  인쇄면에서는
# 구별되지 않는 조판 변덕이므로 **크기가 가르고 굵기는 가르지 않는다.**
#
# 다만 굵기를 열어 주는 만큼 **크기는 좁게 닫는다.**  같은 RyuminPro-Medium 이
# 14.2pt 【 】 괄호, 8.9pt 도해 설명, 9.0/12.3/15.3pt 도해 중괄호(｛)에도 쓰인다 —
# 조금만 열어도 그것들이 예문 뒤에 달라붙는다.  예문은 9.2pt 한 칸뿐이고, 여유는
# PyMuPDF 의 반올림을 흡수할 만큼만 둔다.
BODY_FONTS = ("RyuminPro-Bold", "RyuminPro-Medium")
BODY_TOLERANCE = 0.1                 # 9.2pt 한 칸.  9.0pt(도해 ｛)는 이미 밖이다

# --- 해설 글꼴로 넘어간 예문의 꼬리 ---
# 조판이 예문을 끝맺지 못하고 마지막 몇 글자를 **해설 글꼴(8.9pt Regular)로**
# 흘려 놓은 자리가 한 군데 있다 — 376 쪽 ``…あなた向きだとわたしは思いま`` 다음
# 줄의 ``すよ。``.  글꼴만 보면 그 조각은 해설이 되고 예문은 문장 도중에 끊긴다.
#
# **가르는 것은 줄 간격이다.**  예문의 줄 간격은 17.0pt 이고 해설 뭉치는 예문에서
# 45pt 넘게 떨어져 시작한다 — 전 권을 재 보면 그 사이에 아무것도 없다.  그래서
# '앞 예문이 문장부호로 끝나지 않았고, 예문 줄 간격만큼 아래' 라는 두 조건이
# 동시에 서는 줄은 전 권에서 그 하나뿐이다.
EXAMPLE_PITCH = 17.5                 # 예문 줄 간격(17.0)에 반올림 여유
TERMINATORS = "。！？」』）…"          # 문장이 끝났음을 보이는 글자

# --- 해설 ---
# 중국어 해설과 한국어 해설은 **크기가 같다**(6.4pt).  가르는 것은 글꼴이다.
# 그런데 해설 안에 인용된 일본어(「いろいろ・さんざん・長い時間」)는 그 언어의
# 글꼴이 아니라 **일본어 글꼴로 조판되어 있다.**  글꼴만 보고 고르면 인용된
# 일본어가 통째로 사라진다 — 문법 설명에서 정작 가리키는 말이 없어지는 것이다.
# 그래서 읽는 순서를 따라가며 '지금 어느 언어의 해설인가' 를 이어 간다.
NOTE_SIZE = 6.4
NOTE_LANGUAGE = {"AdobeSong": "zh", "AdobeMyungjo": "ko"}
NOTE_QUOTE_FONT = "RyuminPro-Regular"   # 해설 안에 인용된 일본어
MARGIN_GAP = 8.0                         # 여백 참조 표시와 본문 사이의 틈(pt)
NOTE_JA_SIZE = 8.9

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
KANJI = re.compile(r"[㐀-鿿\U00020000-\U0002A6DF豈-﫿々〆]")


def is_example(font, size):
    """예문 본문인가.  **크기가 가르고 굵기는 가르지 않는다**(``BODY_FONTS``)."""
    return (font.startswith(BODY_FONTS)
            and abs(size - BODY_SIZE) <= BODY_TOLERANCE)


def characters(page):
    """페이지의 모든 글자.  탭은 뺀다.

    **공백을 버리지 않는다.**  영어와 한국어 해설은 공백이 곧 단어 경계여서,
    ``strip()`` 으로 걸러 내면 ``comprisedof`` 처럼 붙어 버린다.
    """
    found = []
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                font = span["font"]
                size = round(span["size"], 1)
                for char in span["chars"]:
                    x0, y0, x1, y1 = char["bbox"]
                    if x0 > SIDE_TAB_X:
                        continue
                    if char["c"] in ("\n", "\r"):
                        continue
                    found.append({
                        "x": x0, "x1": x1, "y": round(y0, 1),
                        "size": size, "font": font, "c": char["c"],
                    })
    return found


def ruby_spans(page):
    """루비는 PDF 가 이미 한자 하나씩 끊어 놓았다.  그 경계를 그대로 쓴다.

    글자 단위로 풀어 다시 묶으면 인접한 루비가 붙어 버려 ``結婚生活(けっこんせいかつ)``
    같은 뭉텅이가 생긴다.  원전은 글자마다 루비를 다는 모노루비이므로 span 경계가
    곧 정답이다.
    """
    found = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                x0, y0, x1, _y1 = span["bbox"]
                text = span["text"].strip()
                if not text or x0 > SIDE_TAB_X:
                    continue
                found.append({"x0": x0, "x1": x1, "y": round(y0, 1),
                              "size": round(span["size"], 1),
                              "font": span["font"], "text": text})
    return found


def group_lines(chars, tolerance=2.5):
    """같은 줄에 놓인 글자끼리 묶는다."""
    lines = []
    for char in sorted(chars, key=lambda c: (c["y"], c["x"])):
        for line in lines:
            if abs(line["y"] - char["y"]) <= tolerance:
                line["chars"].append(char)
                break
        else:
            lines.append({"y": char["y"], "chars": [char]})
    for line in lines:
        line["chars"].sort(key=lambda c: c["x"])
    return sorted(lines, key=lambda l: l["y"])


def annotate(chars, rubies):
    """본문 글자열에 그 위의 루비를 붙여 ``한자(よみ)`` 꼴로 만든다.

    루비 span 의 x 범위에 중심이 들어오는 한자들이 그 루비가 걸리는 글자다.
    한 루비는 한 번만 쓰이므로 붙인 뒤 목록에서 뺀다.
    """
    remaining = list(rubies)
    out = []
    index = 0
    while index < len(chars):
        char = chars[index]
        centre = (char["x"] + char["x1"]) / 2
        hit = None
        if KANJI.match(char["c"]):
            hit = next((r for r in remaining
                        if r["x0"] - 0.8 <= centre <= r["x1"] + 0.8), None)
        if hit is None:
            out.append(char["c"])
            index += 1
            continue
        run = []
        while index < len(chars):
            following = chars[index]
            middle = (following["x"] + following["x1"]) / 2
            if not KANJI.match(following["c"]):
                break
            if not (hit["x0"] - 0.8 <= middle <= hit["x1"] + 0.8):
                break
            run.append(following["c"])
            index += 1
        out.append(f"{''.join(run)}({hit['text']})")
        remaining.remove(hit)
    return "".join(out)


def text_of(chars):
    return "".join(c["c"] for c in chars)


def rubies_above(rubies, y, predicate):
    """본문 줄 ``y`` 바로 위에 놓인 루비들."""
    return [r for r in rubies
            if 0 < y - r["y"] <= RUBY_RISE and predicate(r)]


def extract(document):
    entries = []
    current = None
    note_language = None
    for number in range(FIRST_PAGE, document.page_count):
        page = document[number]
        chars = characters(page)
        if not chars:
            continue
        rubies = ruby_spans(page)
        lines = group_lines(chars)
        spill = None              # 좌표가 쪽마다 새로 시작하므로 꼬리도 쪽 안에서만 잇는다
        for line in lines:
            # --- 표제형: 항목의 시작 ---
            heads = [c for c in line["chars"]
                     if c["size"] == HEAD_SIZE and c["font"].startswith(HEAD_FONT)]
            if heads:
                current = {
                    "head": text_of(heads).strip(),
                    "page": number + 1,
                    "level": "",
                    "gloss_ja": "", "gloss_en": "", "gloss_zh": "", "gloss_ko": "",
                    "connect": [],
                    "examples": [],
                    "note_ja": "", "note_ko": "",
                }
                entries.append(current)
                note_language = None      # 해설 언어 상태는 항목마다 새로 시작한다
            if current is None:
                continue
            rest = [c for c in line["chars"] if c not in heads]
            if not rest:
                continue

            # --- 급수 ---
            level = [c for c in rest if c["font"].startswith(LEVEL_FONT)]
            if level:
                current["level"] += text_of(level)

            # --- 【 】 안의 일본어 뜻 (루비가 붙는다) ---
            gloss = [c for c in rest
                     if c["font"].startswith(GLOSS_FONT) and 7.0 <= c["size"] <= 8.2]
            if gloss:
                above = rubies_above(rubies, line["y"], lambda r: r["size"] < 5.0)
                current["gloss_ja"] += annotate(gloss, above)

            # --- 영 ／ 중 ／ 한 뜻 (5.7pt 한 줄에 슬래시로 나뉜다) ---
            small = [c for c in rest if c["size"] == 5.7
                     and not c["font"].startswith(LEVEL_FONT)]
            if small:
                current["_gloss_line"] = current.get("_gloss_line", "") + text_of(small)

            # --- 접속형.  「＋」 를 낀 것만이 접속형이다 ---
            connect = [c for c in rest if c["font"].startswith(CONNECT_FONT)]
            if connect:
                shape = text_of(connect).strip()
                if "＋" in shape or "+" in shape:
                    current["connect"].append(re.sub(r"\s+", " ", shape))

            # --- 예문 ---
            body = [c for c in rest if is_example(c["font"], c["size"])]
            if not body and spill is not None and 0 < line["y"] - spill <= EXAMPLE_PITCH:
                # 해설 글꼴로 흘러간 예문의 꼬리(``EXAMPLE_PITCH`` 참조).
                tail = [c for c in rest if c["font"].startswith(NOTE_QUOTE_FONT)
                        and c["size"] == NOTE_JA_SIZE]
                # 줄 전체가 예문의 것이다 — 들여쓰기 공백까지 해설에서 걷어 낸다.
                claimed = {id(c) for c in tail}
                # 이어지는 줄의 첫 전각 공백은 들여쓰기다.  낱말 사이에 넣으면 안 된다.
                while tail and tail[0]["c"].isspace():
                    tail.pop(0)
                if tail:
                    rest = [c for c in rest if id(c) not in claimed]
                    body = tail
            if body:
                # 루비는 본문과 **같은 굵기**로 달린다.  Medium 으로 조판된 예문의
                # 루비도 Medium 이므로, 그 줄의 본문이 실제로 쓴 글꼴만 받는다.
                weights = tuple({c["font"] for c in body})
                above = rubies_above(
                    rubies, line["y"],
                    lambda r: r["font"].startswith(weights) and r["size"] <= RUBY_MAX)
                current["examples"].append(annotate(body, above))
                printed = text_of(body).strip()
                spill = (line["y"]
                         if printed and printed[-1] not in TERMINATORS else None)

            # --- 해설 ---
            note_ja = [c for c in rest
                       if c["font"].startswith(NOTE_QUOTE_FONT)
                       and c["size"] == NOTE_JA_SIZE]
            if note_ja:
                current["note_ja"] += text_of(note_ja)

            # 한국어 해설.  6.4pt 를 읽는 순서대로 훑으며 언어 상태를 이어 간다.
            # 언어 글꼴(AdobeSong·AdobeMyungjo)을 만나면 상태가 바뀌고, 그 사이의
            # 일본어 인용은 지금 상태의 해설에 속한다.  한국어는 5.7pt(뜻)에도 같은
            # 글꼴로 나오므로 크기로 먼저 가른다.
            #
            # **줄 첫머리의 인용은 뒤따르는 언어의 것이다.**  상태를 윗줄에서 이어받기만
            # 하면, 중국어 해설 다음 줄이 ``「～とき…」의 형태로`` 처럼 인용으로 시작할 때
            # 그 인용이 중국어 쪽으로 가서 버려진다 — 한국어 해설이 ``의 형태로`` 로
            # 시작하는 항목이 58 개 있었다.  그래서 인용은 잠시 들고 있다가, 다음에 나오는
            # 언어 글꼴의 해설에 붙인다.  줄이 인용으로 끝나면 지금 상태의 해설에 붙인다.
            #
            # 여백의 참조 표시 ``→参`` 은 해설이 아니다.  화살표만 해설 글꼴이고 뒤따르는
            # 「参」 은 작은 글꼴이라, 인용과 함께 들고 있으면 ``→「間」는…`` 처럼 해설
            # 첫머리에 화살표가 붙는다.  바로 뒤에 「参」 이 오는 화살표는 버린다.
            # 「参」 이 다른 줄로 묶이는 일도 있으므로(글꼴이 작아 기준선이 다르다), 줄의
            # 첫 해설 글자인 화살표가 다음 글자와 크게 떨어져 **왼쪽 여백**에 있어도 버린다.
            margin_marks = {id(char) for char, following in zip(rest, rest[1:])
                            if char["c"] == "→" and following["c"] == "参"}
            sized = [c for c in rest if c["size"] == NOTE_SIZE]
            if (len(sized) > 1 and sized[0]["c"] == "→"
                    and sized[1]["x"] - sized[0]["x1"] > MARGIN_GAP):
                margin_marks.add(id(sized[0]))
            korean = []
            pending = []
            for char in (c for c in rest if c["size"] == NOTE_SIZE):
                language = next((value for prefix, value in NOTE_LANGUAGE.items()
                                 if char["font"].startswith(prefix)), None)
                if language is None:
                    if (char["font"].startswith(NOTE_QUOTE_FONT)
                            and id(char) not in margin_marks):
                        pending.append(char)
                    continue          # 6.4pt 의 그 밖의 글꼴은 기호다 — 해설이 아니다
                note_language = language
                if note_language == "ko":
                    korean.extend(pending)
                    korean.append(char)
                pending = []
            if pending and note_language == "ko":
                korean.extend(pending)
            if korean:
                current["note_ko"] += text_of(korean)
    return entries


# 「→参」 「→◆」 처럼 본문 안에서 다른 항목을 가리키는 기호.  뜻의 일부가 아니다.
REFERENCE_MARKS = "参照◆→※"


def split_gloss(entry):
    """5.7pt 한 줄에 붙어 나오는 ``영 ／ 중 ／ 한`` 을 나눈다."""
    line = entry.pop("_gloss_line", "")
    if not line:
        return
    parts = [p.strip() for p in line.split("／")]
    if len(parts) >= 3:
        entry["gloss_en"], entry["gloss_zh"] = parts[0], parts[1]
        entry["gloss_ko"] = "／".join(parts[2:])
    else:
        entry["gloss_en"] = line.strip()
    for name in ("gloss_en", "gloss_zh", "gloss_ko"):
        entry[name] = entry[name].rstrip(REFERENCE_MARKS + " ").strip()


# 해설 안의 인용은 글꼴이 바뀌는 자리라 조판이 「 와 인용문 사이에 공백을 넣는다.
# 인쇄면에서는 자간이지만 텍스트로 뽑으면 「 いろいろ…」 처럼 벌어져 보인다.
QUOTE_GAP = re.compile(r"(?<=「)[ 　]+|[ 　]+(?=」)")


def tighten_quotes(entry):
    """인용 부호 안쪽에 붙은 조판 공백을 지운다.  글자는 건드리지 않는다."""
    for name in ("note_ja", "note_ko"):
        entry[name] = QUOTE_GAP.sub("", entry[name])


def join_examples(entry):
    """번호(①②…)로 시작하는 줄이 예문의 첫 줄.  이어지는 줄은 앞에 붙인다."""
    joined = []
    for line in entry["examples"]:
        if line[:1] in CIRCLED:
            joined.append(line)
        elif joined:
            joined[-1] += line
        else:
            joined.append(line)
    entry["examples"] = [
        {"no": line[0], "ja": line[1:].strip()} for line in joined if line[:1] in CIRCLED
    ]


def main():
    document = pymupdf.open(str(paths.BUNPO_PDF))
    entries = extract(document)
    document.close()
    for entry in entries:
        split_gloss(entry)
        tighten_quotes(entry)
        join_examples(entry)
        entry["level"] = entry["level"].replace("級", "").strip()
    paths.DATA.mkdir(parents=True, exist_ok=True)
    with paths.D1_RAW.open("w", encoding="utf-8") as stream:
        json.dump(entries, stream, ensure_ascii=False, indent=1)
    total = sum(len(e["examples"]) for e in entries)
    print(f"표제형 {len(entries)} | 예문 {total} | -> {paths.D1_RAW.name}")


if __name__ == "__main__":
    main()
