# -*- coding: utf-8 -*-
"""etf/benchmark.py 검증 — 순도·겹침 순수 로직 (오프라인, 손계산 픽스처)."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.benchmark import load_exposures, overlap, purity_metrics  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS" if cond else "FAIL"), name, detail if not cond else "")


# 픽스처: 판정 노출도 A=80%, B=20% (C는 비판정)
expo = pd.Series({"A": 0.8, "B": 0.2})

# ── 1) 손계산: 보유 A 50% / B 30% / C(비판정) 20% ─────────────────────
w = pd.Series({"A": 0.5, "B": 0.3, "C": 0.2})
m = purity_metrics(w, expo)
check("커버리지 = 80%", abs(m["판정커버리지(%)"] - 80.0) < 1e-9)
# 하한 = 0.5×0.8 + 0.3×0.2 = 0.46
check("순도 하한 = 46%", abs(m["순도 하한(%)"] - 46.0) < 1e-9,
      f"got={m['순도 하한(%)']}")
# 커버 내 = 0.46/0.8 = 57.5%
check("커버 내 순도 = 57.5%", abs(m["커버 내 순도(%)"] - 57.5) < 1e-9)

# ── 2) 완전 판정이면 하한 = 커버 내 ───────────────────────────────────
w2 = pd.Series({"A": 0.6, "B": 0.4})
m2 = purity_metrics(w2, expo)
check("완전 커버 시 하한=커버내", abs(m2["순도 하한(%)"] - m2["커버 내 순도(%)"]) < 1e-9)
check("커버리지 100%", abs(m2["판정커버리지(%)"] - 100.0) < 1e-9)

# ── 3) 비정규 비중 입력도 내부 정규화 ──────────────────────────────────
m3 = purity_metrics(w * 7.0, expo)          # 스케일만 다름
check("비중 스케일 불변", abs(m3["순도 하한(%)"] - m["순도 하한(%)"]) < 1e-9)

# ── 4) overlap 손계산 ─────────────────────────────────────────────────
a = pd.Series({"X": 0.7, "Y": 0.3})
b = pd.Series({"X": 0.4, "Z": 0.6})
check("겹침 = min합 = 0.4", abs(overlap(a, b) - 0.4) < 1e-9, f"got={overlap(a,b)}")
check("자기 자신 겹침 = 1", abs(overlap(a, a) - 1.0) < 1e-9)
check("서로소 겹침 = 0",
      abs(overlap(a, pd.Series({"Q": 1.0}))) < 1e-9)

# ── 5) 실데이터 로더: 33종목·범위 검증 ────────────────────────────────
expo_real = load_exposures()
check("판정 노출도 로드 (>= 30종목)", len(expo_real) >= 30, f"n={len(expo_real)}")
check("노출도 범위 [0,1]", bool((expo_real >= 0).all() and (expo_real <= 1).all()),
      f"min={expo_real.min()} max={expo_real.max()}")
check("우리 앵커 포함 (005930·000660)",
      "005930" in expo_real.index and "000660" in expo_real.index)

# ── 6) 입력 방어 ──────────────────────────────────────────────────────
try:
    purity_metrics(pd.Series(dtype=float), expo); check("빈 비중 방어", False)
except ValueError:
    check("빈 비중 방어", True)
try:
    purity_metrics(pd.Series({"A": -0.2, "B": 1.2}), expo)
    check("음수 비중 방어", False)
except ValueError:
    check("음수 비중 방어", True)

print()
print("전부 통과" if ok else "실패 있음")
sys.exit(0 if ok else 1)
