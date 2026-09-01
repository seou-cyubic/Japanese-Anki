"""Native data store with a single-file human-edit overlay."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 계약 오류·해시·차이 계산은 스키마와 무관한 일반 도구다.
from decks.kanji.model import ContractError, diff_values, record_etag
from .persistence import advisory_file_lock, atomic_write_json, file_sha256


class ConflictError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_json_no_duplicates(path: Path) -> Any:
    duplicates: list[str] = []

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in items:
            if key in output:
                duplicates.append(key)
            output[key] = value
        return output

    payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    if duplicates:
        raise ContractError([f"중복 JSON key가 있다: {duplicates[0]}"])
    return payload


class NativeStore:
    """Expose base + overlay as one native current-schema snapshot.

    The browser never edits a legacy projection.  A save commits the complete
    current-schema record to ``edits.v1.json``; materialization is an explicit CLI
    operation so a generated pipeline artifact is not silently overwritten.
    """

    def __init__(self, spec, overlay_path: Path | None = None):
        self.spec = spec
        data_path = spec.data_path
        if overlay_path is None:
            overlay_path = data_path.parent / "edits.v1.json"
        self.data_path = Path(data_path).resolve()
        self.overlay_path = Path(overlay_path).resolve()
        self.lock_path = self.overlay_path.with_suffix(self.overlay_path.suffix + ".lock")
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not self.data_path.exists():
            raise FileNotFoundError(self.data_path)
        base_bytes = self.data_path.read_bytes()
        self.base_newline = "\r\n" if b"\r\n" in base_bytes else "\n"
        self.base_sha256 = file_sha256(self.data_path) or ""
        base = _load_json_no_duplicates(self.data_path)
        errors = self.spec.validate_payload(base)
        if errors:
            raise ContractError(errors)
        self.base: dict[str, dict[str, Any]] = base

        if self.overlay_path.exists():
            overlay = _load_json_no_duplicates(self.overlay_path)
            self._validate_overlay(overlay)
            self.overlay = overlay
            self.overlay_file_sha256 = file_sha256(self.overlay_path)
        else:
            self.overlay = self._empty_overlay()
            self.overlay_file_sha256 = None

        self.overlay_conflict = self.overlay["base_data_sha256"] != self.base_sha256
        self._rebuild_snapshot()

    def _empty_overlay(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "base_data_sha256": self.base_sha256,
            "revision": 0,
            "records": {},
        }

    def _validate_overlay(self, overlay: Any) -> None:
        if not isinstance(overlay, dict):
            raise ContractError(["편집 overlay 최상위 값은 object여야 한다"])
        required = {"schema_version", "base_data_sha256", "revision", "records"}
        if set(overlay) != required:
            raise ContractError(["편집 overlay 필드가 v1 계약과 다르다"])
        if overlay["schema_version"] != 1:
            raise ContractError(["지원하지 않는 편집 overlay schema_version이다"])
        if not isinstance(overlay["base_data_sha256"], str):
            raise ContractError(["overlay base_data_sha256가 문자열이 아니다"])
        if not isinstance(overlay["revision"], int) or overlay["revision"] < 0:
            raise ContractError(["overlay revision이 음이 아닌 정수가 아니다"])
        if not isinstance(overlay["records"], dict):
            raise ContractError(["overlay records가 object가 아니다"])

        for character, entry in overlay["records"].items():
            if not isinstance(entry, dict):
                raise ContractError([f"overlay `{character}` 항목이 object가 아니다"])
            expected = {
                "baseline_etag",
                "baseline",
                "human",
                "reasons",
                "history",
                "updated_at",
            }
            if set(entry) != expected:
                raise ContractError([f"overlay `{character}` 필드가 v1 계약과 다르다"])
            baseline_errors = self.spec.validate_record(character, entry["baseline"])
            human_errors = self.spec.validate_record(character, entry["human"])
            if baseline_errors or human_errors:
                raise ContractError(baseline_errors + human_errors)
            if entry["baseline_etag"] != record_etag(entry["baseline"]):
                raise ContractError([f"overlay `{character}` baseline_etag가 맞지 않는다"])
            if not isinstance(entry["reasons"], list) or not all(
                isinstance(reason, str) and reason for reason in entry["reasons"]
            ):
                raise ContractError([f"overlay `{character}` reasons가 문자열 배열이 아니다"])
            if not isinstance(entry["history"], list):
                raise ContractError([f"overlay `{character}` history가 배열이 아니다"])

    def _rebuild_snapshot(self) -> None:
        effective: dict[str, dict[str, Any]] = dict(self.base)
        for character, entry in self.overlay["records"].items():
            effective[character] = entry["human"]
        self.records = effective
        self.edited = {
            character
            for character, entry in self.overlay["records"].items()
            if entry["human"] != entry["baseline"]
        }
        self.statistics = self.spec.statistics(self.records)
        self.index = self._build_index()

    def _build_index(self) -> list[dict[str, Any]]:
        """검색 색인.  각 줄의 모양은 덱이 정한다 — 여기서는 규약만 지킨다."""
        rows = []
        for key, record in self.records.items():
            row = self.spec.index_row(key, record)
            row["edited"] = key in self.edited
            rows.append(row)
        return rows

    def snapshot(self) -> dict[str, Any]:
        """편집이 반영된 현재 전체 데이터의 사본.  Anki 동기화가 이것을 읽는다."""
        return copy.deepcopy(self.records)

    def bootstrap(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "deck": self.spec.name,
            "title": self.spec.title,
            "record_label": self.spec.record_label,
            "modes": [{"key": key, "label": label} for key, label in self.spec.modes],
            "renderer": self.spec.renderer,
            **self.statistics,
            "edited": len(self.edited),
            "base_data_sha256": self.base_sha256,
            "overlay_revision": self.overlay["revision"],
            "overlay_conflict": self.overlay_conflict,
        }

    def search(self, needle: str, limit: int = 80) -> dict[str, Any]:
        query = needle.strip()
        if not query:
            return {"query": query, "results": [], "total": 0}
        folded = query.casefold()
        priorities = self.spec.search_priorities or {}
        matches: list[tuple[int, dict[str, Any], tuple[str, str, str]]] = []
        for row in self.index:
            found: list[tuple[int, tuple[str, str, str]]] = []
            for term in row["_terms"]:
                text, kind, _ = term
                term_folded = text.casefold()
                if folded not in term_folded:
                    continue
                exact = term_folded == folded
                priority = priorities.get(kind, 5) if exact else 10
                found.append((priority, term))
            if found:
                found.sort(key=lambda item: item[0])
                matches.append((found[0][0], row, found[0][1]))

        matches.sort(key=lambda item: (item[0], -item[1]["weight"], item[1]["key"]))
        results = []
        for priority, row, term in matches[:limit]:
            public = {name: value for name, value in row.items() if name != "_terms"}
            public.update({
                "match_kind": term[1],
                "matched_text": term[0],
                "match_context": term[2],
                "exact_match": priority < 10,
            })
            results.append(public)
        return {"query": query, "results": results, "total": len(matches)}

    def record(self, key: str) -> dict[str, Any]:
        """레코드 하나를 화면이 쓸 모양으로.  투영 방식은 덱이 정한다."""
        found = self.records.get(key)
        if found is None:
            raise KeyError(key)
        projected = self.spec.project_record(
            key, copy.deepcopy(found), edited=key in self.edited)
        projected["overlay_conflict"] = self.overlay_conflict
        return projected

    # 이전 이름.  한자 덱 시절의 호출부가 남아 있을 수 있다.
    character = record

    def history(self, character: str = "", limit: int = 60) -> list[dict[str, Any]]:
        lines: list[dict[str, Any]] = []
        for key, entry in self.overlay["records"].items():
            if character and key != character:
                continue
            for item in entry["history"]:
                lines.append({"character": key, **item})
        lines.sort(key=lambda item: item["at"], reverse=True)
        return lines[:limit]

    def _assert_files_unchanged(self) -> None:
        if file_sha256(self.data_path) != self.base_sha256:
            raise ConflictError(
                f"{self.data_path.name} 이 서버 시작 뒤 바뀌었다. 서버를 다시 시작한다")
        if file_sha256(self.overlay_path) != self.overlay_file_sha256:
            raise ConflictError("편집 overlay가 다른 프로세스에서 바뀌었다. 서버를 다시 시작한다")
        if self.overlay_conflict:
            raise ConflictError("pipeline base와 편집 overlay가 어긋났다. 먼저 rebase해야 한다")

    def save(
        self,
        character: str,
        submitted: Any,
        *,
        expected_etag: str,
        reason: str,
    ) -> dict[str, Any]:
        if not isinstance(reason, str):
            raise ContractError(["저장 사유는 문자열이어야 한다"])
        reason = reason.strip()
        if not reason:
            raise ContractError(["무엇을 왜 고쳤는지 사유를 적어야 저장한다"])
        if len(reason) > 500:
            raise ContractError(["저장 사유는 500자 이하여야 한다"])

        if not isinstance(character, str):
            raise ContractError(["character는 문자열이어야 한다"])
        if not isinstance(expected_etag, str):
            raise ContractError(["record_etag는 문자열이어야 한다"])

        with self._lock, advisory_file_lock(self.lock_path):
            self._assert_files_unchanged()
            current = self.records.get(character)
            if current is None:
                raise KeyError(character)
            if record_etag(current) != expected_etag:
                raise ConflictError("이 글자가 다른 창에서 먼저 수정되었다. 다시 불러온다")
            if not isinstance(submitted, dict):
                raise ContractError(["record는 object여야 한다"])

            after = copy.deepcopy(submitted)
            pipeline = self.base[character]
            # korean_src is provenance, not a free-form editable field.
            if pipeline.get("korean_src") == "gemini" and (
                isinstance(after.get("korean"), dict)
                and after["korean"].get("본") == pipeline["korean"].get("본")
            ):
                after["korean_src"] = "gemini"
            else:
                after.pop("korean_src", None)

            errors = self.spec.validate_record(character, after)
            if errors:
                raise ContractError(errors)
            # 사람이 넣은 용례도 파이프라인과 같은 순서 규칙을 따른다.
            self.spec.sort_record(after)
            after = self.spec.order_record(after)
            changes = diff_values(current, after)
            if not changes:
                return {
                    "ok": True,
                    "changes": 0,
                    "note": "바뀐 것이 없다",
                    "record_etag": record_etag(current),
                }

            overlay = copy.deepcopy(self.overlay)
            entry = overlay["records"].get(character)
            if entry is None:
                entry = {
                    "baseline_etag": record_etag(pipeline),
                    "baseline": copy.deepcopy(pipeline),
                    "human": copy.deepcopy(after),
                    "reasons": [],
                    "history": [],
                    "updated_at": utc_now(),
                }
                overlay["records"][character] = entry
            else:
                entry["human"] = copy.deepcopy(after)
                entry["updated_at"] = utc_now()
            if reason not in entry["reasons"]:
                entry["reasons"].append(reason)
            item = {
                "txn_id": str(uuid.uuid4()),
                "at": utc_now(),
                "reason": reason,
                "changes": changes,
            }
            entry["history"].append(item)
            overlay["revision"] += 1

            new_sha = atomic_write_json(self.overlay_path, overlay, verify=self._validate_overlay)
            self.overlay = overlay
            self.overlay_file_sha256 = new_sha
            self._rebuild_snapshot()
            return {
                "ok": True,
                "changes": len(changes),
                "record_etag": record_etag(after),
                "overlay_revision": overlay["revision"],
                "log": changes,
            }

    def materialize(self, output_path: Path) -> Path:
        with self._lock, advisory_file_lock(self.lock_path):
            self._assert_files_unchanged()
            output = Path(output_path).resolve()
            if output == self.data_path:
                raise ValueError("원본을 직접 덮지 말고 별도 --output 경로를 지정한다")
            payload = copy.deepcopy(self.records)

            def verify(candidate: Any) -> None:
                errors = self.spec.validate_payload(candidate)
                if errors:
                    raise ContractError(errors)

            atomic_write_json(output, payload, verify=verify, newline=self.base_newline)
            return output
