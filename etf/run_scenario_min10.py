# -*- coding: utf-8 -*-
"""
etf/run_scenario_min10.py — 종목수 10 충족 시나리오 리포트
==========================================================
사용법:
    .venv/Scripts/python.exe etf/run_scenario_min10.py

출력: etf/output/scenario_min10.csv (+ 권장안 구성 상세) + 콘솔 리포트
"""
from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.ERROR)     # selection 정보 로그 억제

from etf.scenario_min10 import load_judged, run_all, run_scenario  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "etf", "output")


def main():
    judged = load_judged()
    table = run_all(judged)
    print("[종목수 10 충족 시나리오] 판정완료 33종목 · 팀 엔진(selection→weighting) 재사용")
    print(table.to_string(index=False))

    print("\n[판독]")
    print("  - 위성 임계 완화 단독으론 불가 — 공정·위원회 확인 통과가 현 7종목뿐이라"
          " 걸림돌은 숫자가 아니라 실사 문서다.")
    print("  - S3(핵심 5%): 규칙 정체성('노출도 30%=핵심') 훼손 + 순도 최저.")
    print("  - S4(실사 확대): 문턱 그대로 두고 위성 실사만 넓혀 14종목 PASS."
          " 순도 희석은 위성 합계 상한 18%가 통제 — 방법론 정체성 유지. ★권장")
    print("  - S5(S4+위성 60%): 19종목, 순도 동일 — 분산·용량 여유가 더 필요하면.")
    print("  ※ 실사 확대는 '메모리향 상위 기업이 실사를 통과한다'는 가정 —"
          " 실제로는 대상 기업별 HBM 공정 귀속 매출 문서 확보가 선행돼야 한다.")

    rec = run_scenario(judged, 0.30, 0.70, assume_process_check=True)
    print(f"\n[권장안 S4 구성 상세 — {rec['종목수']}종목, "
          f"순도 {rec['HBM순도(%)']}%]")
    print(rec["_구성"].to_string(index=False))

    os.makedirs(OUT_DIR, exist_ok=True)
    table.to_csv(os.path.join(OUT_DIR, "scenario_min10.csv"),
                 index=False, encoding="utf-8-sig")
    rec["_구성"].to_csv(os.path.join(OUT_DIR, "scenario_min10_S4_구성.csv"),
                      index=False, encoding="utf-8-sig")
    print(f"\n저장: {OUT_DIR}\\scenario_min10.csv, scenario_min10_S4_구성.csv")


if __name__ == "__main__":
    main()
