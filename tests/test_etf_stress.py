# -*- coding: utf-8 -*-
"""etf/stress_test.py 검증 — 오프라인(합성 경로), 손계산 가능한 불변식.

핵심: 하락 구간에서 현금 기여의 부호가 반전(드래그→방어)하는지,
용량이 ADV에 정비례로 줄어드는지, 환매 소화율 공식이 손계산과 맞는지.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.capacity import EOK  # noqa: E402
from etf.stress_test import (drawdown_window, redemption_endurance,  # noqa: E402
                             stress_capacity, stress_capacity_assumptions,
                             stress_tracking)

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS" if cond else "FAIL"), name, detail if not cond else "")


def make_bt_with_crash(n_up=200, n_down=60, n_rec=100) -> pd.DataFrame:
    """상승 → -30% 급락 → 회복 합성 경로 (결정론적)."""
    days = pd.bdate_range("2025-01-02", periods=n_up + n_down + n_rec)
    up = 1000 * (1.004) ** np.arange(n_up)
    down = up[-1] * (1 - 0.006) ** np.arange(1, n_down + 1)
    rec = down[-1] * (1.003) ** np.arange(1, n_rec + 1)
    level = pd.Series(np.concatenate([up, down, rec]), index=days)
    tno = pd.Series(0.0, index=days)
    tno.iloc[63::63] = 0.10
    return pd.DataFrame({"level": level, "turnover": tno, "reason": ""})


bt = make_bt_with_crash()

# ── 1) drawdown_window: 고점·저점 위치와 낙폭 ─────────────────────────
peak_d, trough_d, mdd = drawdown_window(bt["level"])
check("고점 = 상승 구간 마지막 날", peak_d == bt.index[199],
      f"got={peak_d}")
check("저점 = 하락 구간 마지막 날", trough_d == bt.index[259],
      f"got={trough_d}")
expect_mdd = (1 - 0.006) ** 60 - 1
check("MDD ≈ (1-0.6%)^60-1", abs(mdd - expect_mdd) < 1e-9,
      f"got={mdd:.4f} expect={expect_mdd:.4f}")

# ── 2) stress_tracking: 하락 구간 현금 기여 부호 반전 ─────────────────
st = stress_tracking(bt, ter_bp=45, trade_cost_bp=30, cash_weight=0.01)
check("전체 기간 현금 기여 > 0 (상승 우세 경로 = 드래그)",
      st.loc["전체 기간", "현금 기여(bp/년)"] > 0,
      f"got={st.loc['전체 기간', '현금 기여(bp/년)']:.1f}")
check("하락 구간 현금 기여 < 0 (방어)",
      st.loc["하락 구간", "현금 기여(bp/년)"] < 0,
      f"got={st.loc['하락 구간', '현금 기여(bp/년)']:.1f}")
check("TER 기여는 구간 무관 ≈ 45bp (±1)",
      abs(st.loc["하락 구간", "TER 기여(bp/년)"] - 45) < 1.0,
      f"got={st.loc['하락 구간', 'TER 기여(bp/년)']:.2f}")
check("하락 구간 지수수익률 = MDD",
      abs(st.loc["하락 구간", "지수수익률(%)"] / 100 - mdd) < 1e-9)

# ── 3) stress_capacity: ADV 정비례 ────────────────────────────────────
w = pd.Series({"BIG": 0.5, "SML": 0.5})
adv = pd.Series({"BIG": 1000 * EOK, "SML": 10 * EOK})
cap = stress_capacity(w, adv, factors=(1.0, 0.5))
check("용량이 ADV에 정비례 (×0.5 → 절반)",
      abs(cap["용량(억)"].iloc[1] - cap["용량(억)"].iloc[0] / 2) < 0.5,
      cap["용량(억)"].tolist())
check("병목 종목 불변 (SML)", (cap["병목 종목"] == "SML").all())

# ── 3b) 용량 가정 민감도: 참여율·허용일수에도 정비례 ──────────────────
# 기준 20%·5일 대비 10%·3일 = 0.5×0.6 = 0.30배 (손계산)
capa = stress_capacity_assumptions(w, adv, participations=(0.20, 0.10),
                                   day_grid=(5.0, 3.0))
base = float(capa.loc[(capa["참여율"] == "20%")
                      & (capa["청산 허용일수"] == 5.0), "용량(억)"].iloc[0])
tight = float(capa.loc[(capa["참여율"] == "10%")
                       & (capa["청산 허용일수"] == 3.0), "용량(억)"].iloc[0])
check("참여율 10%·3일 = 기준의 0.30배", abs(tight - base * 0.30) < 0.5,
      f"base={base} tight={tight}")
check("기준 대비 배수 표기 정확", capa["기준 대비"].iloc[-1] == "×0.30",
      capa["기준 대비"].tolist())
check("가정 민감도에서도 병목 불변 (SML)", (capa["병목 종목"] == "SML").all())
# ADV 계수와 곱해져야 한다 (두 축은 독립·곱셈)
capa_dry = stress_capacity_assumptions(w, adv, participations=(0.20,),
                                       day_grid=(5.0,), adv_factor=0.5)
check("ADV 계수는 가정 축과 곱셈으로 결합",
      abs(float(capa_dry["용량(억)"].iloc[0]) - base * 0.5) < 0.5,
      f"got={capa_dry['용량(억)'].iloc[0]} expect={base * 0.5}")

# ── 4) redemption_endurance 손계산 ────────────────────────────────────
# AUM 100억, SML 비중 50%→50억 포지션, ADV 10억×0.5×참여20% = 1억/일
# → 소화율 = 1억/50억 = 2%
r = redemption_endurance(w, adv, aum_krw=100 * EOK, adv_factor=0.5)
check("환매 소화율 = 2%/일", abs(r["일일 환매 소화율(%)"] - 2.0) < 1e-9,
      f"got={r['일일 환매 소화율(%)']}")
check("환매 병목 = SML", r["병목 종목"] == "SML")

# ── 5) 방어 ───────────────────────────────────────────────────────────
try:
    drawdown_window(pd.Series([1.0, 2.0]))
    check("짧은 데이터 방어", False)
except ValueError:
    check("짧은 데이터 방어", True)
try:
    mono = pd.Series(np.arange(1, 100, dtype=float),
                     index=pd.bdate_range("2025-01-02", periods=99))
    drawdown_window(mono)
    check("단조 상승(낙폭 없음) 방어", False)
except ValueError:
    check("단조 상승(낙폭 없음) 방어", True)
try:
    redemption_endurance(w, adv, aum_krw=-1)
    check("AUM 음수 방어", False)
except ValueError:
    check("AUM 음수 방어", True)

print()
print("전부 통과" if ok else "실패 있음")
sys.exit(0 if ok else 1)
