# -*- coding: utf-8 -*-
"""
etf/run_global_scenario.py — S6 글로벌 확장: 국내판 vs 글로벌판 나란히

실사 CSV(글로벌후보_실사_20260729.csv)에서 **판정이 완료된 행만** 국내 33종목과
합쳐 팀 엔진(사전 스크린 → 규칙 0/A/C → 비중)을 그대로 태운다. 문턱 무수정 —
해외 종목이라고 규칙을 구부리지 않는다. Micron이 앵커가 되는 것도, TSMC가
어느 군에도 못 드는 것도 전부 규칙이 정한다.

빈칸이 있는 후보는 '미실사'로 제외하고 사유를 출력한다(fail-closed).
실사를 하나도 안 채웠으면 글로벌판 = 국내판이 나오는 것이 정상이다 —
그게 이 러너의 기준선 검증이기도 하다.

한계 (phase 2로 명시적 이월)
  · 용량·CU·추적오차의 글로벌판: 해외 ADV·환율 시계열 파이프라인 필요
  · KRW 환산 지수 산출: 위와 동일
  이 러너는 구성·순도·분산요건(가격 불필요 지표)까지만 낸다.

    .venv/Scripts/python.exe etf/run_global_scenario.py [--judged 경로]

산출: etf/output/global_scenario.csv (+ 글로벌 구성표)
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.global_candidates import (TEMPLATE, load_global_judged,  # noqa: E402
                                   merge_with_korean, write_template)
from etf.run_final import GRANTED  # noqa: E402
from etf.scenario_min10 import load_judged, run_scenario  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "etf", "output")


def main() -> int:
    ap = argparse.ArgumentParser(description="S6 글로벌 확장 시나리오")
    ap.add_argument("--judged", default=TEMPLATE,
                    help="실사 CSV 경로 (기본: 글로벌후보_실사_20260729.csv)")
    args = ap.parse_args()

    if not os.path.exists(args.judged):
        path = write_template(args.judged)
        print(f"실사 템플릿 생성: {path}")
        print("→ 글로벌실사_가이드.md를 따라 채운 뒤 다시 실행하십시오. "
              "빈칸인 후보는 편입되지 않습니다(fail-closed).")
        return 0

    judged_kr = load_judged()
    judged_gl, pending = load_global_judged(args.judged)

    if len(pending):
        print("[미실사 제외] 빈 필드가 있는 후보 — 문서 근거가 채워질 때까지 편입 불가")
        print(pending.to_string(index=False))
        print()

    grants = list(GRANTED)
    r_kr = run_scenario(judged_kr, grant_codes=grants)
    if len(judged_gl):
        merged = merge_with_korean(judged_kr, judged_gl)
        r_gl = run_scenario(merged, grant_codes=grants)
    else:
        r_gl = r_kr
        print("판정 완료된 해외 후보 없음 — 글로벌판 = 국내판 (기준선)\n")

    comp = pd.DataFrame([
        {"판": "국내 (현행)", "종목수": r_kr["종목수"],
         "앵커/핵심/위성": r_kr["앵커/핵심/위성"],
         "HBM순도(%)": r_kr["HBM순도(%)"], "최대비중(%)": r_kr["최대비중(%)"],
         "R1 ≥10": r_kr["R1 종목수≥10"], "R2 ≤30%": r_kr["R2 ≤30%"],
         "R3 ≤20%": r_kr["R3 ≤20%"]},
        {"판": "글로벌 (S6)", "종목수": r_gl["종목수"],
         "앵커/핵심/위성": r_gl["앵커/핵심/위성"],
         "HBM순도(%)": r_gl["HBM순도(%)"], "최대비중(%)": r_gl["최대비중(%)"],
         "R1 ≥10": r_gl["R1 종목수≥10"], "R2 ≤30%": r_gl["R2 ≤30%"],
         "R3 ≤20%": r_gl["R3 ≤20%"]},
    ])
    print("[S6 글로벌 확장 — 같은 규칙, 심사 대상만 확대]")
    print(comp.to_string(index=False))
    print(f"\n[글로벌판 구성 {r_gl['종목수']}종목]")
    print(r_gl["_구성"].to_string(index=False))

    kr_codes = set(judged_kr["코드"].astype(str).str.zfill(6))
    foreign = r_gl["_구성"][~r_gl["_구성"]["코드"].isin(kr_codes)]
    if len(foreign):
        print(f"\n→ 해외 편입 {len(foreign)}종목: "
              + ", ".join(f"{r['종목명']}({r['군']} {r['편입비중(%)']}%)"
                          for _, r in foreign.iterrows()))
    print("\n한계: 용량·CU·추적오차의 글로벌판은 해외 ADV·환율 파이프라인이 갖춰진 뒤 "
          "산출한다(phase 2). 이 표는 구성·순도·분산요건까지다.")

    os.makedirs(OUT_DIR, exist_ok=True)
    comp.to_csv(os.path.join(OUT_DIR, "global_scenario.csv"),
                index=False, encoding="utf-8-sig")
    r_gl["_구성"].to_csv(os.path.join(OUT_DIR, "global_scenario_구성.csv"),
                        index=False, encoding="utf-8-sig")
    print(f"저장: {OUT_DIR}\\global_scenario.csv, global_scenario_구성.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
