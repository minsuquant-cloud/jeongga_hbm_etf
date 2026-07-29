# -*- coding: utf-8 -*-
"""etf/hist_data.py 지수 코어 검증 — 오프라인(합성 가격), D:\\data 불필요.

배경 회귀 2건:
  · 회전율 누락(f3807a5에서 수정): 비중을 매일 목표로 되돌리면 |Δ목표|=0이라
    회전율이 0으로 나왔다 — 매매비용 17bp가 0.2bp처럼 보였다. 분기 재고정
    방식에서 재고정일 회전율이 손계산과 맞는지 지킨다.
  · 룩어헤드 방지(pit_weights): 상장 전 종목을 소급 편입하면 안 된다.
"""
import os
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.hist_data import pit_weights, simulate_reset_index  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS" if cond else "FAIL"), name, detail if not cond else "")


days = pd.bdate_range("2025-01-02", "2025-04-15")   # Q1 말(03-31) 재고정 포함
n = len(days)

# ── 1) pit_weights: 상장 전 비중 0 (룩어헤드 방지) ────────────────────
close = pd.DataFrame({"A": 100.0, "B": np.nan}, index=days)
close.loc["2025-02-03":, "B"] = 50.0                # B는 2월에 상장
w = pit_weights(close, pd.Series({"A": 0.6, "B": 0.4}))
check("상장 전 B 비중 = 0", float(w.loc["2025-01-15", "B"]) == 0.0)
check("상장 전 A가 전량", abs(float(w.loc["2025-01-15", "A"]) - 1.0) < 1e-12)
check("상장 후 목표 비율 복원",
      abs(float(w.loc["2025-03-03", "B"]) - 0.4) < 1e-12,
      float(w.loc["2025-03-03", "B"]))
row_sums = w.sum(axis=1)
check("행 합 = 1 (살아있는 날)", bool((row_sums.sub(1.0).abs() < 1e-12).all()))

# 전 종목 결측일 → 비중 전부 0 (0으로 나누지 않음)
c2 = close.copy()
c2.loc["2025-01-10"] = np.nan
w2 = pit_weights(c2, pd.Series({"A": 0.6, "B": 0.4}))
check("전 종목 결측일은 비중 0", float(w2.loc["2025-01-10"].sum()) == 0.0)

# ── 2) 단일 종목: 지수 = 가격 경로 (레벨 정합) ────────────────────────
px = pd.DataFrame({"A": np.linspace(100.0, 130.0, n)}, index=days)
bt = simulate_reset_index(px, pd.Series({"A": 1.0}))
ratio = bt["level"] / px["A"]
check("단일 종목 지수 = 가격 배율", float(ratio.std()) < 1e-9)
check("단일 종목 회전율 = 0 (되돌릴 drift 없음)",
      float(bt["turnover"].sum()) == 0.0)

# ── 3) 회전율 손계산 (회전율 누락 버그 회귀) ──────────────────────────
# A가 둘째 날 +10% 점프 후 횡보, B는 무변동. 50/50 목표.
# 재고정일(03-31) 표류 비중: A = 0.55/1.05, 회전율 = |0.5-0.5238| = 0.0238
px3 = pd.DataFrame({"A": 100.0, "B": 100.0}, index=days)
px3.loc[days[1]:, "A"] = 110.0
bt3 = simulate_reset_index(px3, pd.Series({"A": 0.5, "B": 0.5}))
reset_d = pd.Timestamp("2025-03-31")
expect = abs(0.5 - 0.55 / 1.05)
check("재고정일 회전율 = 손계산(0.0238)",
      abs(float(bt3.loc[reset_d, "turnover"]) - expect) < 1e-9,
      f"got={float(bt3.loc[reset_d, 'turnover']):.6f} expect={expect:.6f}")
check("재고정일 외 회전율 = 0",
      float(bt3.drop(index=[reset_d, days[-1]])["turnover"].abs().sum()) == 0.0)
check("drift가 있으면 총회전율 > 0 (누락 버그 회귀)",
      float(bt3["turnover"].sum()) > 0.0)

# ── 4) 목표 비중 정규화: 합≠1 입력도 동일 결과 ────────────────────────
bt3b = simulate_reset_index(px3, pd.Series({"A": 5.0, "B": 5.0}))
check("비정규화 target 동일 결과",
      bool((bt3b["level"] - bt3["level"]).abs().max() < 1e-9))

# ── 5) 중도 상장: 다음 재고정 전까지 지수에 무영향 ────────────────────
pxm = pd.DataFrame({"A": np.linspace(100.0, 120.0, n), "B": np.nan},
                   index=days)
pxm.loc["2025-02-03":, "B"] = 50.0                  # 2월 상장, B 무변동
bt5 = simulate_reset_index(pxm, pd.Series({"A": 0.5, "B": 0.5}))
solo = simulate_reset_index(pxm[["A"]], pd.Series({"A": 1.0}))
pre_reset = bt5.loc[:"2025-03-30", "level"]
check("상장~재고정 전 지수 = A 단독 경로",
      bool((pre_reset - solo.loc[:"2025-03-30", "level"]).abs().max() < 1e-9))
check("재고정 후 B 편입 (n_stocks 1→2)",
      int(bt5["n_stocks"].iloc[-1]) == 2
      and int(bt5.loc["2025-03-28", "n_stocks"]) == 1)

# ── 6) 상장폐지: 가격 소멸 후 지수가 깨지지 않는다 ────────────────────
pxd = pd.DataFrame({"A": 100.0, "B": 100.0}, index=days)
pxd.loc["2025-03-03":, "B"] = np.nan                # B 3월 폐지
pxd["A"] = np.linspace(100.0, 120.0, n)
bt6 = simulate_reset_index(pxd, pd.Series({"A": 0.5, "B": 0.5}))
check("폐지 후에도 레벨 유한", bool(np.isfinite(bt6["level"]).all()))
check("폐지 종목은 재고정에서 제외 (n_stocks 2→1)",
      int(bt6["n_stocks"].iloc[-1]) == 1)

# ── 7) FutureWarning 없음 (pct_change pad 회귀) ───────────────────────
with warnings.catch_warnings(record=True) as rec:
    warnings.simplefilter("always")
    simulate_reset_index(px3, pd.Series({"A": 0.5, "B": 0.5}))
    fut = [x for x in rec if issubclass(x.category, FutureWarning)]
check("FutureWarning 없음", len(fut) == 0,
      [str(x.message)[:60] for x in fut])

print()
print("전부 통과" if ok else "실패 있음")
sys.exit(0 if ok else 1)
