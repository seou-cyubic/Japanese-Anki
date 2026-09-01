# -*- coding: utf-8 -*-
"""통합 파이프라인 러너 — 순서대로 5 단계를 실행한다."""
# 이 파일은 **모듈이 아니라 실행 파일이다.**  본문이 최상위에 있어서 import 하는
# 순간 이 스테이지가 통째로 돈다 — 원전을 다시 읽고, 모델을 부르고(유료다), 산출물을
# 덮어쓴다.  이름이 같은 모듈을 잘못 집어 오는 것만으로 그 일이 벌어진 적이 있다.
# 조용히 도는 것보다 시끄럽게 서는 편이 낫다.
# 이 규칙은 tests/test_pipeline_entry.py 가 전 덱에 걸어 둔다.
if __name__ != "__main__":
    raise RuntimeError(
        "이 파일은 스크립트다 — import 하면 그 자리에서 실행된다. "
        "실행은 `python decks/kanji/pipeline/run_all.py`.")

import sys
import subprocess

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

STAGES = [
    ("1", "pipeline/stage1_raw.py"),
    ("2", "pipeline/stage2_korean.py"),
    ("3", "pipeline/stage3_examples.py"),
    ("4", "pipeline/stage4_translate.py"),
    ("5", "pipeline/stage5_japanese.py"),
]

for no, script in STAGES:
    print(f"===== Stage {no}: {script} =====", flush=True)
    r = subprocess.run([sys.executable, "-u", script])
    if r.returncode != 0:
        print(f"Stage {no} 실패 (exit {r.returncode}) — 중단")
        sys.exit(r.returncode)
print("전 파이프라인 완료: data_japanese.json")
