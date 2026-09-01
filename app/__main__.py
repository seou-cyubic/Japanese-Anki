"""Command line entry point for the deck editor."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from shared.deckspec import discover
from shared.paths import DECKS
from shared.store import NativeStore

from .server import DEFAULT_PORT, serve


def open_stores(only: str = "") -> dict[str, NativeStore]:
    """데이터가 준비된 덱을 전부 연다.  파이프라인을 안 돌린 덱은 건너뛴다."""
    stores = {}
    for name, spec in sorted(discover(DECKS).items()):
        if only and name != only:
            continue
        if not spec.data_path.exists():
            print(f"건너뜀: {name} — {spec.data_path.name} 이 없다")
            continue
        stores[name] = NativeStore(spec)
    if not stores:
        raise SystemExit("열 수 있는 덱이 없다. 파이프라인을 먼저 돌린다.")
    return stores


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="python -m app")
    commands = root.add_subparsers(dest="command", required=True)

    def common(command: argparse.ArgumentParser) -> None:
        command.add_argument("--deck", default="", help="이 덱만 연다")

    serve_command = commands.add_parser("serve", help="로컬 편집 서버 실행")
    common(serve_command)
    serve_command.add_argument("--port", type=int, default=DEFAULT_PORT)

    check_command = commands.add_parser("check", help="현재 데이터와 overlay 전수 검증")
    common(check_command)

    materialize = commands.add_parser("materialize", help="base+overlay를 최종 JSON으로")
    common(materialize)
    materialize.add_argument("--output", type=Path, required=True)

    sync_command = commands.add_parser(
        "sync", help="현재 데이터를 Anki 에 반영한다 (파이프라인의 마지막 걸음)")
    common(sync_command)
    return root


def main() -> None:
    # 콘솔이 UTF-8 이 아닐 수 있다(윈도우 기본은 cp949).  덱 이름도 안내문도 한국어라
    # 인코딩에 걸리면 프로그램이 통째로 죽는다 — 글자가 깨질지언정 멈추지는 않는다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = parser().parse_args()
    stores = open_stores(args.deck)
    if args.command == "serve":
        serve(stores, args.port)
        return
    if args.command == "check":
        for name, store in stores.items():
            print(name, json.dumps(store.bootstrap(), ensure_ascii=False, indent=2))
        return
    if args.command == "materialize":
        if len(stores) != 1:
            raise SystemExit("materialize 는 --deck 으로 덱 하나를 지정한다")
        print(next(iter(stores.values())).materialize(args.output))
        return
    if args.command == "sync":
        sync(stores)
        return


def sync(stores: dict[str, NativeStore]) -> None:
    """데이터를 Anki 까지 밀어 넣는다.  **파이프라인은 JSON 에서 끝나지 않는다.**

    산출물만 새로 만들고 멈추면 화면과 Anki 가 갈라진다 — 고친 예문을 정작
    외우는 자리에서는 옛것으로 보게 된다.  그래서 데이터가 바뀌면 여기까지가
    한 번의 수정이다.

    학습 정보는 건드리지 않는다.  추가·갱신·이동만 하고 삭제하지 않으며,
    학습 이력·예약을 만지는 액션은 ``shared/anki.py`` 의 ``FORBIDDEN_ACTIONS`` 가
    아예 부를 수 없게 막아 둔다.
    """
    from shared.anki import Anki, AnkiUnavailable, sync_spec

    anki = Anki(timeout=300)
    try:
        anki("version")
    except AnkiUnavailable as error:
        raise SystemExit(f"Anki 에 닿지 못했다: {error}")
    for name, store in stores.items():
        for row in sync_spec(anki, store.spec, store.snapshot()):
            summary = row["result"]
            print(f"{name} · {row['note_type']}: "
                  + " · ".join(f"{key} {value}" for key, value in summary.items()))


if __name__ == "__main__":
    main()
