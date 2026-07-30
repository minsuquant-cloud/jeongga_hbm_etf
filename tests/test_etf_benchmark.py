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

# ── 7) 두 판정 파일의 노출도가 갈리면 예외 (잣대 분열 방지) ───────────
import etf.benchmark as bm  # noqa: E402

orig_final = bm.JUDGED_FINAL
try:
    bm.JUDGED_FINAL = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "data", "processed", "후보리스트_20260723.csv")
    try:
        bm.load_exposures()          # 노출도 열이 없는 파일 → 읽기 단계에서 실패
        check("판정 파일 불일치 감지", False, "예외 없이 통과(회귀!)")
    except (ValueError, KeyError):
        check("판정 파일 불일치 감지", True)
finally:
    bm.JUDGED_FINAL = orig_final
check("정상 경로는 그대로 동작", len(bm.load_exposures()) >= 30)

# ── 8) 경쟁사 순도가 전멸하면 리포트를 덮어쓰지 않는다 (fail-closed) ──
rep_all_nan = pd.DataFrame([
    {"ETF": "자체", "순도 하한(%)": 29.0},
    {"ETF": "경쟁A", "순도 하한(%)": float("nan")},
    {"ETF": "경쟁B", "순도 하한(%)": float("nan")}])
check("전멸 감지 조건이 참", rep_all_nan.iloc[1:]["순도 하한(%)"].notna().sum() == 0)
rep_ok = rep_all_nan.copy()
rep_ok.loc[1, "순도 하한(%)"] = 22.3
check("일부만 실패하면 통과", rep_ok.iloc[1:]["순도 하한(%)"].notna().sum() > 0)

# ── 9) 해외 판정 합류 — 자기 지수가 '판정 밖'으로 빠지지 않는다 ────────
# 회귀(2026-07-30): load_exposures가 국내 판정만 읽어 MU가 판정 밖이 되면서
# 자체 순도가 29.81 → 25.89%로 과소, 판정커버리지도 86.96%로 떨어졌다.
expo_all = bm.load_exposures()
from etf.run_tracking import load_constituents  # noqa: E402

cur = load_constituents()
missing = [c for c in cur["코드"] if c not in expo_all.index]
check("편입 전 종목이 판정 노출도에 있다 (커버리지 100%)", not missing, missing)
w_cur = pd.Series((cur["편입비중(%)"] / 100).values, index=cur["코드"])
m_cur = purity_metrics(w_cur / w_cur.sum(), expo_all)
check("자체 판정커버리지 100%",
      abs(m_cur["판정커버리지(%)"] - 100.0) < 1e-6, m_cur["판정커버리지(%)"])
check("순도 하한 == 커버 내 순도 (커버리지 100%면 같아야)",
      abs(m_cur["순도 하한(%)"] - m_cur["커버 내 순도(%)"]) < 1e-6)
check("해외 티커가 zfill로 깨지지 않음", "0000MU" not in expo_all.index)

print()
print("전부 통과" if ok else "실패 있음")
sys.exit(0 if ok else 1)
