from __future__ import annotations

import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path

from decks.kanji.model import ContractError
from shared.store import ConflictError, NativeStore


ROOT = Path(__file__).resolve().parents[1]

from tests import load  # noqa: E402


def deck_at(path):
    """임시 경로를 바라보는 덱 계약.  저장소 시험이 실데이터를 건드리지 않게 한다."""
    import dataclasses

    from decks.kanji.deck import DECK
    return dataclasses.replace(DECK, data_path=path)


class StoreTest(unittest.TestCase):
    def setUp(self) -> None:
        source = load("kanji", "data_japanese.json")
        self.temp = tempfile.TemporaryDirectory()
        folder = Path(self.temp.name)
        self.data = folder / "data_japanese.json"
        self.overlay = folder / "edits.v1.json"
        subset = {key: source[key] for key in ("亜", "衣", "祈", "𠮟")}
        self.data.write_text(json.dumps(subset, ensure_ascii=False, indent=2), encoding="utf-8")
        self.original_bytes = self.data.read_bytes()
        self.store = NativeStore(deck_at(self.data), self.overlay)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_noop_does_not_create_overlay(self) -> None:
        view = self.store.character("祈")
        result = self.store.save(
            "祈", view["record"], expected_etag=view["record_etag"], reason="무변경 확인"
        )
        self.assertEqual(result["changes"], 0)
        self.assertFalse(self.overlay.exists())
        self.assertEqual(self.data.read_bytes(), self.original_bytes)

    def test_save_persists_native_overlay_and_materializes_separately(self) -> None:
        """고친 뜻은 **표기를 따라간다** — 자리는 따라가지 않는다.

        저장은 순서를 다시 세운다(``spec.sort_record``).  뜻을 고치면 정렬 열쇠가
        바뀌므로 그 용례는 칸 안에서 자리를 옮길 수 있다 — 그것이 정상이다.  자리로
        찾으면 이 시험은 실데이터의 뜻 길이에 매달려, 뜻 하나가 바뀌는 것만으로
        엉뚱하게 터진다.
        """
        def meaning_of(record, surface):
            for example in record["readings"]["キ"]:
                if example["w"].startswith(surface):
                    return example["ko"]
            raise AssertionError(f"{surface} 가 사라졌다")

        view = self.store.character("祈")
        edited = copy.deepcopy(view["record"])
        edited["readings"]["キ"][0]["ko"] = "소원을 빎"
        target = view["record"]["readings"]["キ"][0]["w"][:2]
        result = self.store.save(
            "祈", edited, expected_etag=view["record_etag"], reason="뜻을 더 정확하게 수정"
        )
        self.assertGreater(result["changes"], 0)
        self.assertTrue(self.overlay.exists())
        self.assertEqual(self.data.read_bytes(), self.original_bytes)

        reloaded = NativeStore(deck_at(self.data), self.overlay)
        self.assertEqual(meaning_of(reloaded.character("祈")["record"], target), "소원을 빎")
        output = Path(self.temp.name) / "materialized.json"
        reloaded.materialize(output)
        materialized = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(meaning_of(materialized["祈"], target), "소원을 빎")

    def test_no_edit_materialization_preserves_base_bytes(self) -> None:
        output = Path(self.temp.name) / "materialized-no-edit.json"
        self.store.materialize(output)
        self.assertEqual(output.read_bytes(), self.original_bytes)

    def test_editing_generated_main_korean_removes_source(self) -> None:
        view = self.store.character("𠮟")
        edited = copy.deepcopy(view["record"])
        edited["korean"]["본"] = ["꾸짖을 질", "나무랄 질"]
        self.store.save(
            "𠮟", edited, expected_etag=view["record_etag"], reason="훈음 보완"
        )
        self.assertNotIn("korean_src", self.store.character("𠮟")["record"])

    def test_stale_record_etag_conflicts(self) -> None:
        view = self.store.character("祈")
        first = copy.deepcopy(view["record"])
        first["readings"]["キ"][0]["ko"] = "첫 수정"
        self.store.save("祈", first, expected_etag=view["record_etag"], reason="첫 저장")
        second = copy.deepcopy(view["record"])
        second["readings"]["キ"][0]["ko"] = "둘째 수정"
        with self.assertRaises(ConflictError):
            self.store.save("祈", second, expected_etag=view["record_etag"], reason="늦은 저장")

    def test_invalid_annotation_is_rejected(self) -> None:
        view = self.store.character("祈")
        edited = copy.deepcopy(view["record"])
        edited["readings"]["キ"][0]["ja"] = "祈願"
        with self.assertRaises(ContractError):
            self.store.save("祈", edited, expected_etag=view["record_etag"], reason="잘못된 저장")

    def test_same_etag_concurrency_has_one_winner(self) -> None:
        view = self.store.character("祈")
        barrier = threading.Barrier(3)
        outcomes: list[str] = []

        def worker(value: str) -> None:
            edited = copy.deepcopy(view["record"])
            edited["readings"]["キ"][0]["ko"] = value
            barrier.wait()
            try:
                self.store.save("祈", edited, expected_etag=view["record_etag"], reason=value)
                outcomes.append("saved")
            except ConflictError:
                outcomes.append("conflict")

        threads = [threading.Thread(target=worker, args=(value,)) for value in ("첫째", "둘째")]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()
        self.assertCountEqual(outcomes, ["saved", "conflict"])

    def test_save_applies_the_ordering_rule(self) -> None:
        """사람이 넣은 용례도 파이프라인과 같은 순서로 정렬되어 저장된다."""
        store = NativeStore(deck_at(self.data), self.overlay)
        record = copy.deepcopy(store.character("亜")["record"])
        record["readings"]["ア"] = [
            {"w": "亜熱帯(あねったい)", "ko": "아열대"},
            {"w": "亜麻(あま)", "ko": "아마"},
        ]
        store.save(
            "亜",
            record,
            expected_etag=store.character("亜")["record_etag"],
            reason="정렬 확인",
        )
        saved = NativeStore(deck_at(self.data), self.overlay).character("亜")["record"]
        self.assertEqual(
            [example["w"] for example in saved["readings"]["ア"]],
            ["亜麻(あま)", "亜熱帯(あねったい)"],
        )


if __name__ == "__main__":
    unittest.main()
