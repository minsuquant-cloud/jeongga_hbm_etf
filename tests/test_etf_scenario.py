# -*- coding: utf-8 -*-
"""etf/scenario_min10.py 검증 — 팀 엔진 재사용 시나리오의 정합성.

핵심 불변식: S0(현행)은 확정 구성표(7종목·순도 35.56%)를 정확히 재현해야
한다 — 시나리오 엔진이 실제 방법론과 같은 결과를 내는지가 신뢰의 근거.
임계값 임시 변경은 반드시 원복돼야 한다(모듈 상수 누수 금지).
"""
import logging
import os
import sys

logging.basicConfig(level=logging.ERROR)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import src.selection as selection  # noqa: E402
from etf.scenario_min10 import load_judged, run_all, run_scenario, thresholds  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS" if cond else "FAIL"), name, detail if not cond else "")


judged = load_judged()

# ── 1) S0 = 확정 구성표 재현 (7종목·순도 35.56%·최대 21.57%) ───────────
s0 = run_scenario(judged)
check("S0 종목수 = 7", s0["종목수"] == 7, f"got={s0['종목수']}")
check("S0 순도 = 35.56%", abs(s0["HBM순도(%)"] - 35.56) < 0.05,
      f"got={s0['HBM순도(%)']}")
check("S0 최대비중 = 21.57%", abs(s0["최대비중(%)"] - 21.57) < 0.05)
check("S0 R1 = FAIL", s0["R1 종목수≥10"] == "FAIL")
check("S0 군 구성 2/4/1", s0["앵커/핵심/위성"] == "2/4/1")

# ── 2) 위성 임계 완화 '단독'은 무효 (공정확인 없는 종목뿐) ─────────────
s_sat = run_scenario(judged, core_th=0.30, sat_mem_th=0.50)
check("위성 60→50% 단독 완화 = 종목수 그대로 7", s_sat["종목수"] == 7,
      f"got={s_sat['종목수']}")

# ── 3) 핵심 문턱 인하: 종목수 증가·순도 감소 단조 ──────────────────────
s1 = run_scenario(judged, core_th=0.15)
s3 = run_scenario(judged, core_th=0.05)
check("핵심 15% → 종목수 8", s1["종목수"] == 8, f"got={s1['종목수']}")
check("핵심 5% → 종목수 12 = R1 PASS",
      s3["종목수"] == 12 and s3["R1 종목수≥10"] == "PASS")
check("문턱 인하 시 순도 단조 감소",
      s0["HBM순도(%)"] > s1["HBM순도(%)"] > s3["HBM순도(%)"],
      f"{s0['HBM순도(%)']} > {s1['HBM순도(%)']} > {s3['HBM순도(%)']}")

# ── 4) 실사 확대(S4): 문턱 유지·14종목·PASS, 원본 불변 ────────────────
before_flags = int(judged["HBM공정확인"].sum())
s4 = run_scenario(judged, assume_process_check=True)
check("S4 종목수 = 14 (2/4/8)", s4["종목수"] == 14
      and s4["앵커/핵심/위성"] == "2/4/8", s4["앵커/핵심/위성"])
check("S4 R1 = PASS", s4["R1 종목수≥10"] == "PASS")
check("S4 순도 > 핵심5%안 (규칙 유지가 덜 희석)",
      s4["HBM순도(%)"] > s3["HBM순도(%)"],
      f"{s4['HBM순도(%)']} vs {s3['HBM순도(%)']}")
check("입력 DataFrame 불변 (실사 플래그 원본 오염 없음)",
      int(judged["HBM공정확인"].sum()) == before_flags)

# ── 5) 임계값 원복 (컨텍스트 누수 금지) ────────────────────────────────
check("run 후 CORE_TH 원복", selection.CORE_TH == 0.30,
      f"got={selection.CORE_TH}")
check("run 후 SAT_MEM_TH 원복", selection.SAT_MEM_TH == 0.70)
try:
    with thresholds(0.01, 0.01):
        raise RuntimeError("boom")
except RuntimeError:
    pass
check("예외 시에도 원복 (finally)", selection.CORE_TH == 0.30
      and selection.SAT_MEM_TH == 0.70)

# ── 6) run_all: 시나리오 6종 전부 + weighting 자체검증 통과 ────────────
table = run_all(judged)
check("시나리오 6종 실행", len(table) == 6, f"len={len(table)}")
check("모든 시나리오 R2 PASS (30% 상한)",
      (table["R2 ≤30%"] == "PASS").all())

print()
print("전부 통과" if ok else "실패 있음")
sys.exit(0 if ok else 1)
