# -*- coding: utf-8 -*-
"""Stage 1: toeic.json — NGSL 1.2 + TSL 1.2 를 한 목록으로 합친다.

두 목록은 **한 낱말도 겹치지 않는다.**  TSL 은 NGSL 을 전제로 그 위에 얹도록 설계된
모듈이기 때문이다.  그래서 합집합이 곧 덱 크기이고, 여기서는 겹침이 정말 없는지를
확인한 뒤 이어 붙이기만 한다 — 겹치는 것이 나오면 전제가 깨진 것이므로 빌드를 세운다.

모델을 부르지 않는다.  이 단계는 결정적이다.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from decks.toeic.pipeline import paths  # noqa: E402
from shared.gemini import dump_json_atomic  # noqa: E402

# 빈도대.  Anki 하위 덱과 편집기 뱃지가 같은 값을 쓴다.
BANDS = [(1000, "1-1000"), (2000, "1001-2000"), (10 ** 9, "2001-2809")]


def read_csv(path: Path) -> list[list[str]]:
    """원전 CSV.  주석 줄(``##``)과 빈 줄을 뺀다.

    NGSL_12_stats.csv 에는 latin-1 바이트가 섞여 있어 UTF-8 로만 읽으면 터진다.
    """
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            rows = list(csv.reader(path.open(encoding=encoding)))
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"{path} 를 읽을 수 없다")
    return [row for row in rows if row and row[0].strip()
            and not row[0].startswith("##")]


def families(path: Path) -> dict[str, list[str]]:
    """표제어 -> 어족.  ``absence,absences`` 한 줄이 한 낱말의 굴절형 전부다."""
    found: dict[str, list[str]] = {}
    for row in read_csv(path)[1:] if False else read_csv(path):
        forms = [cell.strip() for cell in row if cell.strip()]
        if not forms:
            continue
        head = forms[0].lower()
        if head in found:
            raise ValueError(f"어족 목록에 표제어가 두 번 나온다: {head}")
        found[head] = forms
    return found


def sfi_of(row: list[str]) -> float | None:
    if len(row) < 3:
        return None
    try:
        return float(row[2])
    except ValueError:
        return None


def band_of(rank: int) -> str:
    for limit, label in BANDS:
        if rank <= limit:
            return label
    return BANDS[-1][1]


def build() -> dict:
    entries: dict[str, dict] = {}
    for source, stats_path, family_path in (
            ("ngsl", paths.NGSL_STATS, paths.NGSL_FAMILY),
            ("tsl", paths.TSL_STATS, paths.TSL_FAMILY)):
        family = families(family_path)
        rows = read_csv(stats_path)
        header, body = rows[0], rows[1:]
        if header[0].strip().lower() not in ("lemma", "word"):
            raise ValueError(f"{stats_path.name}: 첫 칸이 표제어가 아니다 — {header}")
        for row in body:
            word = row[0].strip().lower()
            rank = int(row[1])
            if word in entries:
                raise ValueError(
                    f"두 목록이 겹친다: {word} ({entries[word]['list']} / {source})")
            entries[word] = {
                "list": source,
                "rank": rank,
                # SFI 는 원전이 주는 빈도 지표다.  덱은 쓰지 않지만 근거로 남긴다.
                # 원전에 `#N/A` 가 섞여 있으므로 숫자가 아니면 비운다.
                "sfi": sfi_of(row),
                "band": band_of(rank) if source == "ngsl" else "TSL",
                "family": family.get(word, [row[0].strip()]),
                "senses": [],
            }
    return entries


def main() -> None:
    entries = build()
    ngsl = sum(1 for e in entries.values() if e["list"] == "ngsl")
    tsl = len(entries) - ngsl
    paths.DATA.mkdir(parents=True, exist_ok=True)
    dump_json_atomic(paths.RAW, entries)
    print(f"NGSL {ngsl} + TSL {tsl} = {len(entries)} 표제어 | 겹침 0 | -> {paths.RAW.name}")


if __name__ == "__main__":
    main()
