# -*- coding: utf-8 -*-
"""backtest 엔진의 거래일 정합 가드 검증 — 오프라인(합성 가격).

배경(2026-07-27 점검): 이벤트 시행일이 가격 인덱스에 없으면 `if d in ev`가
영원히 거짓이 되어 이벤트가 **예외 없이 사라졌다**. 최초 이벤트가 비거래일이면
지수가 base(1000)에 평평하게 고정된 채로 정상 반환됐다. 가격 결측에는
ValueError를 던지는 fail-closed 엔진에서 이 경로만 열려 있었다.

또한 ann_vol/correlation만 pct_change()를 인자 없이 써서 결측을 ffill로
삼켰다(변동성 과소계상 + pandas FutureWarning).
"""
import os
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backtest.backtest import (ann_vol, correlation, make_event,  # noqa: E402
                               simulate_index)

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS" if cond else "FAIL"), name, detail if not cond else "")


days = pd.bdate_range("2025-01-06", periods=40)          # 월~금만
px = pd.DataFrame({"A": np.linspace(100.0, 140.0, 40),
                   "B": np.linspace(50.0, 40.0, 40)}, index=days)
w0 = pd.Series({"A": 0.5, "B": 0.5})
w1 = pd.Series({"A": 0.9, "B": 0.1})

# ── 1) 정상 경로: 거래일 이벤트는 그대로 동작 ─────────────────────────
bt = simulate_index(px, [make_event(days[0], "regular", w0),
                         make_event(days[10], "regular", w1)])
check("거래일 이벤트는 정상 반영", float(bt["turnover"].sum()) > 0,
      float(bt["turnover"].sum()))
check("레벨이 평평하지 않음", bt["level"].nunique() > 1)

# ── 2) 중간 이벤트가 비거래일이면 예외 (조용히 삭제 금지) ─────────────
sat = pd.Timestamp("2025-01-25")                          # 토요일
assert sat not in px.index
try:
    simulate_index(px, [make_event(days[0], "regular", w0),
                        make_event(sat, "regular", w1)])
    check("비거래일 이벤트 → 예외", False, "조용히 무시됨(회귀!)")
except ValueError as e:
    check("비거래일 이벤트 → 예외", "거래일이 아닙니다" in str(e), str(e)[:60])

# ── 3) 최초 이벤트가 비거래일이면 예외 (지수 전체 평평 방지) ──────────
sun = pd.Timestamp("2025-01-05")                          # 표본 시작 전 일요일
try:
    bad = simulate_index(px, [make_event(sun, "regular", w0)])
    check("최초 이벤트 비거래일 → 예외", False,
          f"레벨 고정 {bad['level'].nunique()}종(회귀!)")
except ValueError:
    check("최초 이벤트 비거래일 → 예외", True)

# ── 4) 예외 메시지에 문제 날짜가 찍힌다 (디버깅 가능성) ───────────────
try:
    simulate_index(px, [make_event(days[0], "regular", w0),
                        make_event(sat, "regular", w1)])
except ValueError as e:
    check("예외에 문제 날짜 표기", "2025-01-25" in str(e), str(e)[:80])

# ── 5) dict 형식(하위호환) 입력도 같은 가드를 받는다 ──────────────────
try:
    simulate_index(px, {days[0]: w0, sat: w1})
    check("dict 입력도 가드 적용", False, "조용히 무시됨(회귀!)")
except ValueError:
    check("dict 입력도 가드 적용", True)

# ── 6) ann_vol/correlation: 결측을 ffill로 삼키지 않는다 ──────────────
s = pd.Series([100.0, 101.0, np.nan, 103.0, 104.0, 105.0] * 10,
              index=pd.bdate_range("2025-01-06", periods=60))
with warnings.catch_warnings(record=True) as rec:
    warnings.simplefilter("always")
    v_na = ann_vol(s)
    fut = [x for x in rec if issubclass(x.category, FutureWarning)]
check("ann_vol에 FutureWarning 없음", len(fut) == 0,
      [str(x.message)[:50] for x in fut])
# 옛 동작(pct_change 기본 'pad')은 결측일 수익률을 0으로 깔아 변동성을 낮춘다.
# 그 값과 달라야 ffill을 안 쓴 것이다. (fill_method=None은 결측 앞뒤 수익률을
# 버리므로 s.dropna() 값과도 다르다 — 간극을 잇지 않는 쪽이 옳다.)
v_ffill = float(s.ffill().pct_change(fill_method=None).dropna()
                .std(ddof=1) * np.sqrt(252))
check("ann_vol이 결측을 ffill하지 않음", abs(v_na - v_ffill) > 1e-6,
      f"현재 {v_na:.6f} == ffill {v_ffill:.6f} (회귀!)")
check("ffill은 변동성을 과소계상한다(문제의 크기)", v_ffill < v_na,
      f"ffill {v_ffill:.4f} vs 현재 {v_na:.4f}")

b = pd.Series(np.linspace(10.0, 20.0, 60), index=s.index)
with warnings.catch_warnings(record=True) as rec:
    warnings.simplefilter("always")
    correlation(s, b)
    fut2 = [x for x in rec if issubclass(x.category, FutureWarning)]
check("correlation에 FutureWarning 없음", len(fut2) == 0,
      [str(x.message)[:50] for x in fut2])

print()
print("전부 통과" if ok else "실패 있음")
sys.exit(0 if ok else 1)
