# -*- coding: utf-8 -*-
"""etf/nav_sim.py 검증 — 전부 오프라인(합성 bt), 네트워크 불필요.

핵심 불변식
  1) 비용이 0이면 NAV는 지수와 완전히 일치 (추적오차 0)
  2) 드래그 분해는 로그 항등 분해 — 합계 = 실측 (경로 무관)
  3) TER 기여는 지수 경로와 무관하게 명목 TER와 일치 (달력일 계상 검증)

경로 의존 함정 회귀: 초기 버전은 산술 CAGR 갭으로 기대값을 세워 하락장 합성
데이터에서 비용 갭이 0.778배로 일그러졌다(지수 성과와 곱으로 얽힘). 분해를
로그 공간 항등식으로 바꿔 해결 — 이 테스트가 그 회귀를 지킨다.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.nav_sim import (drag_decomposition, scenario_grid,  # noqa: E402
                         simulate_etf_nav, tracking_report)

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS" if cond else "FAIL"), name, detail if not cond else "")


def make_bt(n=504, drift=0.0006, vol=0.012, seed=7,
            event_every=63, event_turnover=0.10) -> pd.DataFrame:
    """합성 지수 bt. vol=0이면 결정론적(상승 5bp/일) 경로."""
    days = pd.bdate_range("2024-07-01", periods=n)
    if vol == 0:
        level = pd.Series(1000 * (1 + drift) ** np.arange(n), index=days)
    else:
        rng = np.random.default_rng(seed)
        level = pd.Series(1000 * np.exp(np.cumsum(rng.normal(drift, vol, n))),
                          index=days)
    tno = pd.Series(0.0, index=days)
    tno.iloc[event_every::event_every] = event_turnover
    return pd.DataFrame({"level": level, "turnover": tno, "reason": ""})


bt_rand = make_bt()                               # 확률 경로 (시드 7: 하락장)
bt_up = make_bt(drift=0.0005, vol=0)              # 결정론적 상승 경로
yrs = (bt_rand.index[-1] - bt_rand.index[0]).days / 365.25

# ── 1) 무비용이면 NAV = 지수 (스케일만 다름) ───────────────────────────
nav0 = simulate_etf_nav(bt_rand, ter_bp=0, trade_cost_bp=0, cash_weight=0)
ratio = (nav0 / nav0.iloc[0]) / (bt_rand["level"] / bt_rand["level"].iloc[0])
check("무비용 NAV = 지수 (최대괴리 < 1e-12)", float((ratio - 1).abs().max()) < 1e-12,
      f"max={float((ratio-1).abs().max()):.2e}")

# ── 2) TER 기여 = 명목 TER — 지수 경로(상승/하락)와 무관 ───────────────
for name, bt_ in (("하락장", bt_rand), ("상승장", bt_up)):
    nav_t = simulate_etf_nav(bt_, ter_bp=30, trade_cost_bp=0)
    dd = drag_decomposition(bt_, nav_t, 30, 0, 0)
    check(f"TER 30bp 기여 ≈ 30bp ({name}, ±0.5bp)",
          abs(dd["TER 기여(bp/년)"] - 30.0) < 0.5,
          f"got={dd['TER 기여(bp/년)']:.3f}")
    check(f"TER만일 때 실측 갭 = TER 기여 ({name})",
          abs(dd["실측 갭(로그 bp/년)"] - dd["TER 기여(bp/년)"]) < 1e-9)

# ── 3) 매매비용 기여 ≈ 비용 × 연율화회전율 (경로 무관) ─────────────────
nav_c = simulate_etf_nav(bt_rand, ter_bp=0, trade_cost_bp=30)
dd_c = drag_decomposition(bt_rand, nav_c, 0, 30, 0)
expect = 30.0 * dd_c["연율화 편도회전율"]
check("비용 30bp 기여 ≈ 30bp×연회전율 (±0.1bp)",
      abs(dd_c["매매비용 기여(bp/년)"] - expect) < 0.1,
      f"got={dd_c['매매비용 기여(bp/년)']:.3f} expect={expect:.3f}")

# ── 4) 분해 항등식: 합계 = 실측 (전 요소 동시, 양 경로) ────────────────
for name, bt_ in (("하락장", bt_rand), ("상승장", bt_up)):
    nav_all = simulate_etf_nav(bt_, ter_bp=30, trade_cost_bp=30, cash_weight=0.02)
    dd = drag_decomposition(bt_, nav_all, 30, 30, 0.02)
    parts = dd["TER 기여(bp/년)"] + dd["매매비용 기여(bp/년)"] + dd["현금 기여(bp/년)"]
    check(f"분해 합계 = 실측 (항등, {name})",
          abs(parts - dd["실측 갭(로그 bp/년)"]) < 1e-9)

# ── 5) 현금 드래그 부호: 상승장 + / 하락장 - (현금이 방어) ─────────────
nav_cu = simulate_etf_nav(bt_up, ter_bp=0, trade_cost_bp=0, cash_weight=0.02)
dd_cu = drag_decomposition(bt_up, nav_cu, 0, 0, 0.02)
check("상승장 현금 기여 > 0 (드래그)", dd_cu["현금 기여(bp/년)"] > 0,
      f"got={dd_cu['현금 기여(bp/년)']:.2f}")
nav_cd = simulate_etf_nav(bt_rand, ter_bp=0, trade_cost_bp=0, cash_weight=0.02)
dd_cd = drag_decomposition(bt_rand, nav_cd, 0, 0, 0.02)
check("하락장 현금 기여 < 0 (방어)", dd_cd["현금 기여(bp/년)"] < 0,
      f"got={dd_cd['현금 기여(bp/년)']:.2f}")

# ── 6) 추적오차 리포트 (확률 경로) ─────────────────────────────────────
rep0 = tracking_report(bt_rand, nav0, 0, 0, 0)
nav_all = simulate_etf_nav(bt_rand, ter_bp=30, trade_cost_bp=30, cash_weight=0.02)
rep1 = tracking_report(bt_rand, nav_all, 30, 30, 0.02)
check("무비용 추종오차 = 0 (1e-6 미만)", rep0["추종오차(연율)"] < 1e-6,
      f"te={rep0['추종오차(연율)']:.2e}")
check("비용 있으면 추종오차 > 0", rep1["추종오차(연율)"] > 0)
check("상관계수 ≈ 1 (같은 지수 추종)", rep1["일간 수익률 상관계수"] > 0.999)

# ── 7) 시나리오 그리드: 행 수 + TER 단조성 ─────────────────────────────
grid = scenario_grid(bt_rand, ter_bps=(15, 30), cost_bps=(10, 30),
                     cash_weights=(0.0,))
check("그리드 행 수 = 2×2×1", len(grid) == 4, f"len={len(grid)}")
g10 = grid[grid["매매비용(bp)"] == 10].sort_values("TER(bp)")
check("TER 증가 → 실측 갭 단조 증가",
      g10["실측 갭(로그 bp/년)"].is_monotonic_increasing)

# ── 8) 입력 방어 ──────────────────────────────────────────────────────
try:
    simulate_etf_nav(bt_rand, cash_weight=1.5); check("cash_weight 범위 방어", False)
except ValueError:
    check("cash_weight 범위 방어", True)
try:
    simulate_etf_nav(bt_rand.drop(columns=["turnover"]))
    check("turnover 누락 방어", False)
except ValueError:
    check("turnover 누락 방어", True)
try:
    simulate_etf_nav(bt_rand, ter_bp=-1); check("음수 보수 방어", False)
except ValueError:
    check("음수 보수 방어", True)


# ── 해외 차등 체결비용 (S6 이월 — MU는 해외 수수료 + 환전 스프레드) ────
bt_fr = make_bt(n=252, vol=0, event_every=63, event_turnover=0.10).copy()
bt_fr["turnover_foreign"] = bt_fr["turnover"] * 0.4      # 회전의 40%가 해외

nav_same = simulate_etf_nav(bt_fr, ter_bp=0, trade_cost_bp=30, cash_weight=0)
nav_none = simulate_etf_nav(bt_fr, ter_bp=0, trade_cost_bp=30, cash_weight=0,
                            foreign_cost_bp=30)
check("해외비용 = 국내비용이면 동일 NAV",
      float((nav_same - nav_none).abs().max()) < 1e-6)

nav_hi = simulate_etf_nav(bt_fr, ter_bp=0, trade_cost_bp=30, cash_weight=0,
                          foreign_cost_bp=80)
check("해외비용↑ → NAV 하락", float(nav_hi.iloc[-1]) < float(nav_same.iloc[-1]))

# 손계산: 해외 40%에 +50bp → 추가 비용 = 0.4×총회전율×50bp
d_same = drag_decomposition(bt_fr, nav_same, 0, 30, 0)
d_hi = drag_decomposition(bt_fr, nav_hi, 0, 30, 0, foreign_cost_bp=80)
yrs = (bt_fr.index[-1] - bt_fr.index[0]).days / 365.25
expect = 0.4 * float(bt_fr["turnover"].sum()) * 50 / yrs      # bp/년
got = d_hi["매매비용 기여(bp/년)"] - d_same["매매비용 기여(bp/년)"]
check("추가 비용 손계산 일치 (0.4×회전×50bp)", abs(got - expect) < 0.5,
      f"got={got:.2f} expect={expect:.2f}")

# 항등 분해가 차등 비용에서도 유지되는가
check("차등 비용에서도 합계 = 실측 (항등)",
      abs(d_hi["실측 갭(로그 bp/년)"] - (d_hi["TER 기여(bp/년)"]
          + d_hi["매매비용 기여(bp/년)"] + d_hi["현금 기여(bp/년)"])) < 1e-6)

# turnover_foreign 없으면 조용히 무시 (하위호환)
bt_kr = bt_fr.drop(columns=["turnover_foreign"])
check("turnover_foreign 없으면 하위호환",
      float((simulate_etf_nav(bt_kr, ter_bp=0, trade_cost_bp=30,
                              foreign_cost_bp=80) - nav_same).abs().max()) < 1e-9)

try:
    simulate_etf_nav(bt_fr, foreign_cost_bp=-1)
    check("음수 해외비용 방어", False)
except ValueError:
    check("음수 해외비용 방어", True)

bad = bt_fr.copy(); bad["turnover_foreign"] = bad["turnover"] * 2
try:
    simulate_etf_nav(bad, trade_cost_bp=30, foreign_cost_bp=50)
    check("해외회전 > 총회전 방어", False)
except ValueError:
    check("해외회전 > 총회전 방어", True)

print()
print("전부 통과" if ok else "실패 있음")
sys.exit(0 if ok else 1)
