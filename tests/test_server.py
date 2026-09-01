from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from app.server import make_server
from shared.store import NativeStore


ROOT = Path(__file__).resolve().parents[1]

from tests import load  # noqa: E402


def deck_at(path):
    """임시 경로를 바라보는 덱 계약.  저장소 시험이 실데이터를 건드리지 않게 한다."""
    import dataclasses

    from decks.kanji.deck import DECK
    return dataclasses.replace(DECK, data_path=path)


class HTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = load("kanji", "data_japanese.json")
        cls.temp = tempfile.TemporaryDirectory()
        folder = Path(cls.temp.name)
        cls.data = folder / "data_japanese.json"
        cls.overlay = folder / "edits.v1.json"
        cls.data.write_text(
            json.dumps({key: source[key] for key in ("亜", "衣", "生", "祈", "𠮟")}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        cls.server = make_server(NativeStore(deck_at(cls.data), cls.overlay), 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.temp.cleanup()

    def get(self, path: str) -> tuple[int, dict | bytes, dict]:
        try:
            response = urllib.request.urlopen(self.base + path, timeout=3)
        except urllib.error.HTTPError as error:
            body = error.read()
            return error.code, json.loads(body), dict(error.headers)
        body = response.read()
        headers = dict(response.headers)
        if headers.get("Content-Type", "").startswith("application/json"):
            return response.status, json.loads(body), headers
        return response.status, body, headers

    def test_static_allowlist_and_security_headers(self) -> None:
        # tokens.css 는 셸도 덱 렌더러도 Anki 노트 타입도 함께 읽는 디자인 토큰이다.
        for path in ("/", "/app.js", "/style.css", "/tokens.css",
                     "/deck/kanji/card.js", "/deck/kanji/card.css"):
            status, _, headers = self.get(path)
            self.assertEqual(status, 200)
            self.assertIn("Content-Security-Policy", headers)
            self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        for path in ("/data_japanese.json", "/secrets/key.json",
                     "/%2e%2e/data_japanese.json", "/deck/kanji/store.py"):
            status, _, _ = self.get(path)
            self.assertEqual(status, 404)

    def test_native_bootstrap_search_and_character(self) -> None:
        status, boot, _ = self.get("/api/kanji/bootstrap")
        self.assertEqual(status, 200)
        self.assertEqual(boot["characters"], 5)
        status, result, _ = self.get("/api/kanji/search?q=" + urllib.parse.quote("亞"))
        self.assertEqual(status, 200)
        self.assertEqual(result["results"][0]["key"], "亜")
        self.assertEqual(result["results"][0]["match_kind"], "variant")
        path = "/api/kanji/record/" + urllib.parse.quote("𠮟", safe="")
        status, record, _ = self.get(path)
        self.assertEqual(status, 200)
        self.assertEqual(record["character"], "𠮟")
        self.assertIn("korean_src", record["record"])
        self.assertNotIn("strokes", record["record"])

        status, result, _ = self.get("/api/kanji/search?q=" + urllib.parse.quote("弥生"))
        self.assertEqual(status, 200)
        self.assertEqual(result["results"][0]["key"], "生")
        self.assertEqual(result["results"][0]["match_kind"], "word")
        self.assertEqual(result["results"][0]["matched_text"], "弥生")

    def test_save_requires_json_and_reason(self) -> None:
        request = urllib.request.Request(self.base + "/api/kanji/save", data=b"{}", method="POST")
        try:
            urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 415)

        _, record, _ = self.get("/api/kanji/record/" + urllib.parse.quote("祈", safe=""))
        payload = {
            "schema_version": 1,
            "key": "祈",
            "record_etag": record["record_etag"],
            "reason": "",
            "record": record["record"],
        }
        request = urllib.request.Request(
            self.base + "/api/kanji/save",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 400)
            body = json.loads(error.read())
            self.assertTrue(body["errors"])


if __name__ == "__main__":
    unittest.main()
