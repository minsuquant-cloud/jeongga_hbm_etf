# -*- coding: utf-8 -*-
"""etf/capacity.py 검증 — 전부 오프라인(합성 ADV), 네트워크 불필요.

핵심 불변식: 용량 = min(허용일수×참여율×ADV/비중), 병목 = argmin.
손계산 가능한 수치로 공식 자체를 검증한다.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.capacity import EOK, capacity_table, max_aum  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS" if cond else "FAIL"), name, detail if not cond else "")


# 손계산 픽스처: 대형(비중 50%, ADV 1000억) / 중형(40%, 100억) / 소형(10%, 5억)
w = pd.Series({"BIG": 0.50, "MID": 0.40, "SML": 0.10})
adv = pd.Series({"BIG": 1000 * EOK, "MID": 100 * EOK, "SML": 5 * EOK})

# ── 1) capacity_table 손계산 (AUM 1000억, 참여율 20%) ──────────────────
tbl = capacity_table(w, adv, aum_krw=1000 * EOK, participation=0.20)
# SML: 포지션 100억, 일일 소화 5×0.2=1억 → 청산 100일
check("소형주 청산 소요일 = 100일", abs(tbl.loc["SML", "청산 소요일"] - 100.0) < 1e-9,
      f"got={tbl.loc['SML','청산 소요일']}")
# BIG: 포지션 500억, 일일 소화 200억 → 2.5일
check("대형주 청산 소요일 = 2.5일", abs(tbl.loc["BIG", "청산 소요일"] - 2.5) < 1e-9)
check("포지션/ADV 배수 (SML 100/5=20배)",
      abs(tbl.loc["SML", "포지션/ADV(배)"] - 20.0) < 1e-9)

# ── 2) 리밸런싱 관점: |Δw|만 거래 ─────────────────────────────────────
dw = pd.Series({"BIG": 0.02, "MID": 0.02, "SML": 0.01})
tbl_r = capacity_table(w, adv, aum_krw=1000 * EOK, participation=0.20,
                       rebalance_dw=dw)
# SML: 거래 10억 ÷ 1억/일 = 10일
check("소형주 리밸 소요일 = 10일",
      abs(tbl_r.loc["SML", "리밸런싱 소요일"] - 10.0) < 1e-9,
      f"got={tbl_r.loc['SML','리밸런싱 소요일']}")

# ── 3) max_aum: 병목 종목과 용량 손계산 ────────────────────────────────
summary, per_stock = max_aum(w, adv, participation=0.20, max_days=5.0)
# 종목별 허용 AUM = 5×0.2×ADV/w → BIG 2000억, MID 250억, SML 50억 → min=SML 50억
check("병목 = 소형주", summary["병목 종목"] == "SML", summary["병목 종목"])
check("용량 = 50억", abs(summary["용량(억)"] - 50.0) < 1e-9,
      f"got={summary['용량(억)']}")
check("종목별 허용 AUM (BIG 2000억)",
      abs(per_stock["BIG"] / EOK - 2000.0) < 1e-9)

# ── 4) 단조성: 참여율↑·허용일수↑ → 용량↑ ─────────────────────────────
s2, _ = max_aum(w, adv, participation=0.25, max_days=5.0)
s3, _ = max_aum(w, adv, participation=0.20, max_days=10.0)
check("참여율 증가 → 용량 증가", s2["용량(억)"] > summary["용량(억)"])
check("허용일수 증가 → 용량 비례 증가",
      abs(s3["용량(억)"] - 2 * summary["용량(억)"]) < 1e-9)

# ── 5) 입력 방어 ──────────────────────────────────────────────────────
try:
    capacity_table(w * 2, adv, 100 * EOK); check("비중 합≠1 방어", False)
except ValueError:
    check("비중 합≠1 방어", True)
try:
    capacity_table(w, adv.drop("SML"), 100 * EOK); check("ADV 누락 방어", False)
except ValueError:
    check("ADV 누락 방어", True)
try:
    bad = adv.copy(); bad["SML"] = 0.0
    capacity_table(w, bad, 100 * EOK); check("ADV 0 방어", False)
except ValueError:
    check("ADV 0 방어", True)
try:
    capacity_table(w, adv, 100 * EOK, participation=1.5)
    check("참여율 범위 방어", False)
except ValueError:
    check("참여율 범위 방어", True)

print()
print("전부 통과" if ok else "실패 있음")
sys.exit(0 if ok else 1)
