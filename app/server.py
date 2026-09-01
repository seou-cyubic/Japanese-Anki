"""Loopback-only HTTP server for the native Japanese data editor."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from decks.kanji.model import ContractError
from shared.store import ConflictError, NativeStore


def all_decks():
    """``decks/`` 아래의 모든 덱 선언.  덱 이름을 하드코딩하지 않는다."""
    from shared.deckspec import discover
    from shared.paths import DECKS
    return discover(DECKS)


def current_deck():
    """지금 **편집** 중인 덱.  편집 화면은 아직 한자 덱 전용이다.

    Anki 동기화는 편집과 달리 전 덱을 대상으로 한다 — ``all_decks()`` 를 쓴다.
    """
    from decks.kanji.deck import DECK
    return DECK


def deck_payload(spec, store):
    """덱의 현재 데이터.  편집 overlay 가 반영된 store 를 우선한다."""
    if store is not None:
        return store.snapshot()
    if spec.load_payload is not None:
        return spec.load_payload()
    raise FileNotFoundError(spec.data_path)


STATIC = Path(__file__).resolve().parent / "static"
STATIC_ROUTES = {
    "/": (STATIC / "index.html", "text/html; charset=utf-8"),
    "/index.html": (STATIC / "index.html", "text/html; charset=utf-8"),
    "/app.js": (STATIC / "app.js", "application/javascript; charset=utf-8"),
    "/style.css": (STATIC / "style.css", "text/css; charset=utf-8"),
    # 디자인 토큰.  덱 렌더러(card.css)와 Anki 노트 타입이 같은 값을 여기서 읽는다.
    "/tokens.css": (STATIC / "tokens.css", "text/css; charset=utf-8"),
}
MIME = {".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8"}


def deck_asset(deck: str, name: str) -> tuple[Path, str] | None:
    """덱 전용 렌더러는 그 덱 폴더에서 낸다.  셸(app)과 덱 자산을 섞지 않는다."""
    if name not in ("card.js", "card.css"):
        return None
    spec = all_decks().get(deck)
    if spec is None:
        return None
    path = spec.static_dir / name
    return (path, MIME[path.suffix]) if path.exists() else None
MAX_BODY = 256 * 1024
# AnkiConnect 애드온이 8765 를 쓴다.  편집기는 비켜 준다.
DEFAULT_PORT = 8770


class EditorHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], stores: dict[str, NativeStore]):
        super().__init__(address, Handler)
        self.stores = stores


class Handler(BaseHTTPRequestHandler):
    server: EditorHTTPServer

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    @property
    def stores(self) -> dict[str, NativeStore]:
        return self.server.stores

    def store_for(self, name: str) -> NativeStore | None:
        return self.stores.get(name)

    def _headers(self, content_type: str, length: int, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
        )
        self.end_headers()

    def send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._headers("application/json; charset=utf-8", len(body), status)
        self.wfile.write(body)

    def send_static(self, path: Path, mime: str) -> None:
        if not path.exists():
            self.send_json({"error": "정적 자산이 없다"}, HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        self._headers(mime, len(body), HTTPStatus.OK)
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = unquote(parsed.path)
        query = parse_qs(parsed.query)
        if route in STATIC_ROUTES:
            path, mime = STATIC_ROUTES[route]
            self.send_static(path, mime)
            return
        if route == "/api/decks":
            self.send_json({"decks": [store.bootstrap()
                                      for store in self.stores.values()]})
            return
        if route == "/api/anki/status":
            self.send_json(anki_status(self.stores))
            return

        # /deck/<덱>/<자산>  ·  /api/<덱>/<...>
        parts = [p for p in route.strip("/").split("/") if p]
        if len(parts) == 3 and parts[0] == "deck":
            asset = deck_asset(parts[1], parts[2])
            if asset:
                self.send_static(*asset)
                return
        if len(parts) >= 2 and parts[0] == "api":
            store = self.store_for(parts[1])
            if store is None:
                self.send_json({"error": f"`{parts[1]}` 덱이 없다"}, HTTPStatus.NOT_FOUND)
                return
            tail = parts[2:]
            if tail == ["bootstrap"]:
                self.send_json(store.bootstrap())
                return
            if tail == ["search"]:
                self.send_json(store.search(query.get("q", [""])[0]))
                return
            if tail == ["log"]:
                self.send_json({"lines": store.history(query.get("key", [""])[0])})
                return
            if len(tail) >= 2 and tail[0] == "record":
                key = "/".join(tail[1:])
                try:
                    self.send_json(store.record(key))
                except KeyError:
                    self.send_json({"error": f"`{key}` 는 이 덱에 없다"},
                                   HTTPStatus.NOT_FOUND)
                return
        self.send_json({"error": "없는 경로"}, HTTPStatus.NOT_FOUND)

    def _anki_sync(self) -> None:
        """계획을 세워 그대로 반영한다.  추가·갱신만 하고 삭제는 하지 않는다."""
        from shared.anki import Anki, AnkiError, AnkiUnavailable, sync_spec

        wanted = urlparse(self.path).query
        target = parse_qs(wanted).get("deck", [""])[0]
        anki = Anki(timeout=300)
        done = []
        try:
            for name, spec in sorted(all_decks().items()):
                if target and name != target:
                    continue
                try:
                    payload = deck_payload(spec, self.stores.get(name))
                except FileNotFoundError:
                    continue                      # 아직 파이프라인을 안 돌린 덱
                for row in sync_spec(anki, spec, payload):
                    done.append({"name": name, **row})
        except AnkiUnavailable as error:
            self.send_json({"error": str(error)}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        except AnkiError as error:
            self.send_json({"error": f"Anki 가 거절했다: {error}"}, HTTPStatus.BAD_GATEWAY)
            return
        self.send_json({"ok": True, "decks": done})

    def _same_origin(self) -> bool:
        host = self.headers.get("Host", "")
        hostname = host.rsplit(":", 1)[0].strip("[]").lower()
        if hostname not in {"127.0.0.1", "localhost", "::1"}:
            return False
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parsed = urlparse(origin)
        return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        parts = [p for p in route.strip("/").split("/") if p]
        saving = len(parts) == 3 and parts[0] == "api" and parts[2] == "save"
        if route != "/api/anki/sync" and not saving:
            self.send_json({"error": "없는 경로"}, HTTPStatus.NOT_FOUND)
            return
        if not self._same_origin():
            self.send_json({"error": "로컬 same-origin 요청만 허용한다"}, HTTPStatus.FORBIDDEN)
            return
        if route == "/api/anki/sync":
            self._anki_sync()
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self.send_json({"error": "Content-Type은 application/json이어야 한다"}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
            return
        try:
            size = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.send_json({"error": "Content-Length가 올바르지 않다"}, HTTPStatus.BAD_REQUEST)
            return
        if size <= 0:
            self.send_json({"error": "JSON 본문이 비었다"}, HTTPStatus.BAD_REQUEST)
            return
        if size > MAX_BODY:
            self.send_json({"error": "요청 본문이 너무 크다"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        try:
            body = json.loads(self.rfile.read(size).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json({"error": "본문이 UTF-8 JSON이 아니다"}, HTTPStatus.BAD_REQUEST)
            return
        if not isinstance(body, dict):
            self.send_json({"error": "저장 본문은 object여야 한다"}, HTTPStatus.BAD_REQUEST)
            return
        expected = {"schema_version", "key", "record_etag", "reason", "record"}
        if set(body) != expected or body.get("schema_version") != 1:
            self.send_json({"error": "저장 본문이 API v1 계약과 다르다"}, HTTPStatus.BAD_REQUEST)
            return
        if not isinstance(body.get("key"), str) or not isinstance(body.get("record_etag"), str):
            self.send_json({"error": "key와 record_etag는 문자열이어야 한다"}, HTTPStatus.BAD_REQUEST)
            return
        if not isinstance(body.get("reason"), str) or not isinstance(body.get("record"), dict):
            self.send_json({"error": "reason은 문자열, record는 object여야 한다"}, HTTPStatus.BAD_REQUEST)
            return
        store = self.store_for(parts[1])
        if store is None:
            self.send_json({"error": f"`{parts[1]}` 덱이 없다"}, HTTPStatus.NOT_FOUND)
            return
        try:
            result = store.save(
                body.get("key", ""),
                body.get("record"),
                expected_etag=body.get("record_etag", ""),
                reason=body.get("reason", ""),
            )
        except KeyError:
            self.send_json({"error": "그 레코드는 현재 데이터에 없다"}, HTTPStatus.NOT_FOUND)
        except ContractError as error:
            self.send_json(
                {"error": "값의 모양이 현재 데이터 계약과 다르다", "errors": error.errors},
                HTTPStatus.BAD_REQUEST,
            )
        except ConflictError as error:
            self.send_json({"error": str(error), "conflict": True}, HTTPStatus.CONFLICT)
        else:
            self.send_json(result)


def anki_status(stores: dict[str, NativeStore]) -> dict[str, Any]:
    """Anki 가 붙어 있는지와, 지금 반영하면 각 덱에서 무엇이 바뀌는지."""
    from shared.anki import Anki, AnkiUnavailable, plan_sync

    anki = Anki()
    try:
        anki("version")
    except AnkiUnavailable as error:
        return {"available": False, "reason": str(error), "decks": []}

    decks = []
    for name, spec in sorted(all_decks().items()):
        for group in spec.anki_notes:
            row = {"name": name, "title": spec.title, "deck": spec.anki_deck,
                   "note_type": group.note_type.name}
            try:
                notes = group.build(deck_payload(spec, stores.get(name)))
                row["notes"] = len(notes)
                row["plan"] = plan_sync(anki, group.note_type, notes,
                                        spec.anki_deck).summary()
                # 노트가 그대로여도 카드가 옛 모습일 수 있다.  그것도 보여 준다.
                row["note_type_drift"] = anki.template_drift(group.note_type)
            except FileNotFoundError:
                row["reason"] = "아직 데이터가 없다. 파이프라인을 먼저 돌린다."
            except Exception as error:             # noqa: BLE001 — 화면에 그대로 보인다
                row["reason"] = str(error)
            decks.append(row)
    return {"available": True, "decks": decks}


def make_server(stores, port: int = DEFAULT_PORT) -> EditorHTTPServer:
    if isinstance(stores, NativeStore):          # 덱 하나만 넘겨도 받아 준다
        stores = {stores.spec.name: stores}
    return EditorHTTPServer(("127.0.0.1", port), stores)


def serve(stores, port: int = DEFAULT_PORT) -> None:
    server = make_server(stores, port)
    address, actual_port = server.server_address
    print(f"http://{address}:{actual_port}")
    for name, store in server.stores.items():
        counts = store.statistics
        size = counts.get("records", counts.get("characters", 0))
        print(f"  {name:6} {store.spec.title:4} 레코드 {size} · 예문 "
              f"{counts.get('examples', 0)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
