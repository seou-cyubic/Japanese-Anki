# -*- coding: utf-8 -*-
"""갓 받은 저장소에서 벌어지면 안 되는 일 둘.

1. 스테이지 스크립트가 **읽히는 것만으로 실행되는 것** (`PipelineEntryTest`)
2. 산출물이 없다고 시험이 **터지는 것** (`ProductionDataAccessTest`)

둘 다 '아직 아무것도 돌리지 않은 상태' 를 고장으로 만든다.  그 상태는 정상이다 —
원전도 산출물도 저장소에 없으므로 받자마자는 언제나 거기서 시작한다.

--- 1. 파이프라인 스크립트는 import 만으로 돌아갈 수 없다 ---

스테이지 스크립트는 원전을 다시 읽고, 모델을 부르고(유료다), 산출물을 덮어쓴다.
그런데 본문이 최상위에 있으면 그 일이 **import 하는 것만으로** 벌어진다 — 이름이
같은 모듈(`stage2_korean`)을 다른 덱에서 잘못 집어 오는 것으로 충분했다.  조용히
돌아가는 것은 최악이다: 부른 쪽은 함수 하나를 가져왔다고 믿는다.

들어오는 문은 둘 중 하나여야 한다.
  1. 최상위에서 아무것도 하지 않고 `main()` 을 `__main__` 아래에서만 부른다
     (문법·토익 덱), 또는
  2. 최상위에서 일을 하되 **import 되면 그 자리에서 선다** (한자 덱).

이 시험은 코드를 **읽어서** 잰다.  실제로 import 해 보는 시험은 가드가 사라진 순간
그 시험 자체가 파이프라인을 돌려 버리므로 쓸 수 없다.

--- 2. 산출물은 `tests/__init__.py` 를 거쳐서만 읽는다 ---

경로를 직접 열면 갓 받은 저장소에서 `FileNotFoundError` 로 터진다.  `load()` 를
거치면 없을 때 건너뛴다.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 최상위에 있으면 '일을 하는' 문장들.  함수 정의 안은 세지 않는다.
WORKING = (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)


def scripts() -> list[Path]:
    found = []
    for pipeline in sorted((ROOT / "decks").glob("*/pipeline")):
        found.extend(sorted(pipeline.glob("stage*.py")))
        found.extend(sorted(pipeline.glob("run_all.py")))
    return found


def runs_a_stage(node: ast.stmt) -> bool:
    """이 최상위 문장이 **스테이지를 돌리는가.**

    표시는 둘이다 — 최상위 반복문, 그리고 이름으로 부르는 문장(`print(...)`).
    둘 다 '이 파일은 읽히는 순간 일을 한다' 는 뜻이다.

    ``sys.path.insert(...)`` 같은 import 채비는 여기에 걸리지 않는다(속성 호출이다).
    상수 대입과 정의만 있는 파일도 마찬가지로 순수 모듈이다 —
    `stage3_reading_keys.py` 가 그렇고, 시험이 그것을 그대로 import 한다.
    """
    if isinstance(node, WORKING):
        return True
    return (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name))


def does_work_at_import(tree: ast.Module) -> bool:
    return any(runs_a_stage(node) for node in tree.body)


def refuses_import(tree: ast.Module) -> bool:
    """`if __name__ != "__main__": raise` 가 **일을 시작하기 전에** 있는가."""
    for node in tree.body:
        if runs_a_stage(node):
            return False
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        test = node.test
        if (isinstance(test.left, ast.Name) and test.left.id == "__name__"
                and any(isinstance(op, ast.NotEq) for op in test.ops)
                and any(isinstance(statement, ast.Raise) for statement in node.body)):
            return True
    return False


def joins_the_data_folder(tree: ast.Module) -> bool:
    """``... / "data" / ...`` 처럼 산출물 폴더를 경로로 짚는가.

    문자열을 찾지 않고 **경로를 잇는 자리**를 본다.  ``"data": ...`` 같은 노트 필드
    이름이나 이 파일 자신의 검사 문구가 걸려들지 않는다.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
            continue
        for side in (node.left, node.right):
            if isinstance(side, ast.Constant) and side.value == "data":
                return True
    return False


class PipelineEntryTest(unittest.TestCase):
    def test_every_pipeline_script_declares_how_it_is_entered(self) -> None:
        checked = 0
        for path in scripts():
            checked += 1
            with self.subTest(script=str(path.relative_to(ROOT))):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                if does_work_at_import(tree):
                    self.assertTrue(
                        refuses_import(tree),
                        "최상위에서 스테이지를 돌리는 스크립트는 import 를 거절해야 한다 — "
                        "`if __name__ != \"__main__\": raise` 를 일을 시작하기 전에 둔다")
        self.assertGreater(checked, 10, "파이프라인 스크립트를 하나도 찾지 못했다")

    def test_the_guard_stands_before_any_work(self) -> None:
        """가드가 뒤에 있으면 아무것도 막지 못한다.  첫 줄들 안에 있어야 한다."""
        for path in scripts():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if not (does_work_at_import(tree) and refuses_import(tree)):
                continue
            with self.subTest(script=str(path.relative_to(ROOT))):
                guard = next(index for index, node in enumerate(tree.body)
                             if isinstance(node, ast.If)
                             and isinstance(node.test, ast.Compare)
                             and isinstance(node.test.left, ast.Name)
                             and node.test.left.id == "__name__")
                for node in tree.body[:guard]:
                    self.assertNotIsInstance(node, WORKING)


class ProductionDataAccessTest(unittest.TestCase):
    """시험은 산출물을 **`tests/__init__.py` 를 거쳐서만** 읽는다.

    ``decks/*/data/*.json`` 은 저장소에 없다 — 원전의 파생물이라 올리지 않기
    때문이다.  경로를 직접 열면 갓 받은 저장소에서 터지고, 진짜 실패와 섞여 처음
    받은 사람이 무엇이 잘못됐는지 알 수 없게 된다.  ``load()``·``deck_data()`` 를
    거치면 없을 때 조용히 건너뛴다.
    """

    def test_no_test_reaches_into_a_deck_data_folder(self) -> None:
        for path in sorted((ROOT / "tests").glob("*.py")):
            if path.name == "__init__.py":       # 여기가 그 유일한 통로다
                continue
            with self.subTest(test=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                self.assertFalse(
                    joins_the_data_folder(tree),
                    "산출물은 tests/__init__.py 의 load()·deck_data() 로만 읽는다")


if __name__ == "__main__":
    unittest.main()
