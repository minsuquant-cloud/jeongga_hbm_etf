# -*- coding: utf-8 -*-
"""etf/scenario_exposure_floor.py 검증 — 오프라인(합성 판정).

계약:
  · 하한 0 = 현행과 완전 동일 (시나리오가 가짜 변화를 만들지 않는다)
  · 하한은 **위성에만** 적용 — 앵커(규칙 0)·핵심(규칙 A)은 무영향
  · 동결 엔진 무수정으로 같은 결과 (선분류 → 제외 → 재실행)
  · 하한을 올릴수록 순도는 단조 증가, 종목수는 단조 감소
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.scenario_exposure_floor import (apply_exposure_floor,  # noqa: E402
                                         compare, run_floor)

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS" if cond else "FAIL"), name, detail if not cond else "")


def jrow(name, code, 유형="장비", 양산=False, 노출=0.5, 메모리=0.8,
         공정=True, 위원회=True, 시총=50_000.0, ff=0.6):
    return {"종목명": name, "코드": code, "시가총액": 시총, "FF": ff,
            "유동시총": 시총 * ff, "거래대금": 500.0, "PER": 10.0, "PBR": 1.0,
            "자본잠식": False, "유형": 유형, "HBM양산": 양산, "HBM노출도": 노출,
            "메모리향비중": 메모리, "HBM공정확인": 공정, "위원회확인": 위원회,
            "감사의견": "적정", "관리종목": False}


JUDGED = pd.DataFrame([
    jrow("앵커A", "005930", 유형="메모리제조", 양산=True, 노출=0.02,   # 저노출 앵커
         메모리=0.55, 시총=15_000_000.0, ff=0.78),
    jrow("핵심A", "042700", 노출=0.60, 시총=200_000.0),
    jrow("핵심B", "089030", 노출=0.31, 시총=150_000.0),
    jrow("위성고", "112290", 노출=0.12, 메모리=0.75, 시총=30_000.0),
    jrow("위성중", "253590", 노출=0.05, 메모리=0.90, 시총=25_000.0),
    jrow("위성저", "425040", 노출=0.00, 메모리=0.80, 시총=20_000.0),
])

# ── 1) 하한 0 = 현행 ──────────────────────────────────────────────────
cand, dropped = apply_exposure_floor(JUDGED, 0.0)
check("하한 0이면 제외 없음", len(cand) == len(JUDGED) and len(dropped) == 0)
base = run_floor(JUDGED, 0.0)
check("하한 0 라벨", base["노출도 하한"] == "없음(현행)")
check("현행 6종목 전원 편입", base["종목수"] == 6, base["종목수"])

# ── 2) 하한은 위성에만 — 저노출 앵커는 살아남는다 ─────────────────────
r10 = run_floor(JUDGED, 0.10)
comp = r10["_구성"].set_index("종목명")
check("저노출 앵커(0.02)는 하한 10%에도 유지",
      "앵커A" in comp.index and comp.at["앵커A", "군"] == "앵커")
check("핵심은 무영향 (문턱 30%가 이미 하한보다 높다)",
      {"핵심A", "핵심B"} <= set(comp.index))
check("위성 중 노출도 <10% 만 탈락",
      set(r10["_탈락"]["종목명"]) == {"위성중", "위성저"},
      r10["_탈락"]["종목명"].tolist())
check("위성고(0.12)는 생존", "위성고" in comp.index)

# ── 3) 경계값: 하한과 정확히 같으면 통과 (미만이 제외) ────────────────
r5 = run_floor(JUDGED, 0.05)
check("노출도 == 하한이면 생존 (위성중 0.05)",
      "위성중" in r5["_구성"]["종목명"].tolist(),
      r5["_구성"]["종목명"].tolist())
check("노출도 < 하한만 제외 (위성저 0.00)",
      set(r5["_탈락"]["종목명"]) == {"위성저"})

# ── 4) 단조성: 하한↑ → 종목수↓, 순도↑ ────────────────────────────────
tbl, _ = compare(JUDGED, (0.0, 0.03, 0.05, 0.10))
n = tbl["종목수"].tolist()
p = tbl["HBM순도(%)"].tolist()
check("종목수 단조 감소", all(a >= b for a, b in zip(n, n[1:])), n)
check("순도 단조 증가", all(a <= b + 1e-9 for a, b in zip(p, p[1:])), p)
check("비교표 행 수 = 하한 수", len(tbl) == 4)

# ── 5) 비중 합은 항상 100 (재배분이 새는지) ───────────────────────────
for f in (0.0, 0.03, 0.05, 0.10):
    s = run_floor(JUDGED, f)["_구성"]["편입비중(%)"].sum()
    check(f"하한 {f:.0%} 비중 합 100", abs(s - 100.0) < 0.05, s)

# ── 6) 입력 방어 ──────────────────────────────────────────────────────
try:
    apply_exposure_floor(JUDGED, 35)          # % 표기 사고
    check("하한 범위 방어", False)
except ValueError:
    check("하한 범위 방어", True)

# ── 7) 실데이터 회귀: 현행(하한 0)이 정본 13종목과 일치 ───────────────
from etf.global_candidates import (load_global_judged,  # noqa: E402
                                   merge_with_korean)
from etf.run_final import GRANTED  # noqa: E402
from etf.run_rebalance_review import load_judged_kr  # noqa: E402
from etf.run_tracking import load_constituents  # noqa: E402

gl, _ = load_global_judged()
real = merge_with_korean(load_judged_kr(), gl) if len(gl) else load_judged_kr()
r0 = run_floor(real, 0.0, grant_codes=list(GRANTED))
cur = load_constituents()
check("하한 0 = 정본 구성과 동일한 종목집합",
      set(r0["_구성"]["코드"]) == set(cur["코드"]),
      sorted(set(r0["_구성"]["코드"]) ^ set(cur["코드"])))
check("하한 0 = 정본 13종목", r0["종목수"] == len(cur), r0["종목수"])

print()
print("전부 통과" if ok else "실패 있음")
sys.exit(0 if ok else 1)
