# -*- coding: utf-8 -*-
"""토익 파이프라인을 1 -> 3 순서로 돌린다.

Stage 2 만 모델을 쓰고, 그 호출은 전부 ``data/cache.json`` 에 남는다.  그래서 두 번째
실행부터는 신규 호출이 0 이고 1·3 은 언제나 공짜다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STAGES = ["stage1_lists.py", "stage2_senses.py", "stage3_verify.py",
          "stage4_examples.py"]


def main() -> None:
    for stage in STAGES:
        print(f"\n=== {stage} ===", flush=True)
        result = subprocess.run([sys.executable, str(HERE / stage)], cwd=str(ROOT))
        if result.returncode != 0:
            raise SystemExit(f"{stage} 가 실패했다 (exit {result.returncode})")


if __name__ == "__main__":
    main()
