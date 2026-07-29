# -*- coding: utf-8 -*-
"""etf/export_basket.py 검증 — 오프라인(합성 구성표), D:\\data 접근 없음.

전량 교체 인계의 가드:
  · 비중 합·중복·결측 검증 (깨진 바스켓은 만들지 않는다)
  · 해외 티커는 등록부 통화·거래소 필수 — 모르면 예외 (원화 주문 사고 방지)
  · 메타 sha256 = 바스켓 내용 해시 (소비자 무결성 검사용)
  · 원자적 쓰기: 검증 실패가 기존 파일을 건드리지 않는다
"""
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.export_basket import (BASKET_COLS, _atomic_write,  # noqa: E402
                               build_basket)
from etf.global_candidates import registry  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS" if cond else "FAIL"), name, detail if not cond else "")


REG = registry()


def comp(rows):
    return pd.DataFrame(rows, columns=["종목명", "코드", "군", "편입비중(%)"])


GOOD = comp([("삼성전자", "005930", "앵커", 40.0),
             ("Micron Technology", "MU", "앵커", 30.0),
             ("한미반도체", "042700", "핵심", 30.0)])

# ── 1) 정상 경로 ──────────────────────────────────────────────────────
basket, meta = build_basket(GOOD, REG, "2026-12-14", source="테스트구성표.csv")
check("컬럼 규격", list(basket.columns) == BASKET_COLS, list(basket.columns))
check("국내 = KRW/KRX",
      basket.set_index("코드").at["005930", "통화"] == "KRW"
      and basket.set_index("코드").at["005930", "거래소"] == "KRX")
check("해외 = 등록부 통화·거래소",
      basket.set_index("코드").at["MU", "통화"] == "USD"
      and "NASDAQ" in basket.set_index("코드").at["MU", "거래소"])
check("메타 계약 필드",
      meta["swap_mode"] == "full_replace" and meta["effective_date"] == "2026-12-14"
      and meta["n_foreign"] == 1 and meta["n_stocks"] == 3)
import hashlib  # noqa: E402

recalc = hashlib.sha256(basket.to_csv(index=False).encode("utf-8-sig")).hexdigest()
check("sha256 = 바스켓 내용 해시", meta["sha256"] == recalc)

# ── 2) fail-closed 검증들 ─────────────────────────────────────────────
bad_sum = comp([("삼성전자", "005930", "앵커", 40.0),
                ("한미반도체", "042700", "핵심", 30.0)])   # 합 70
try:
    build_basket(bad_sum, REG, "2026-12-14", "x")
    check("비중 합 ≠ 100 예외", False)
except ValueError as e:
    check("비중 합 ≠ 100 예외", "100" in str(e))

dup = comp([("삼성전자", "005930", "앵커", 50.0),
            ("삼성전자", "005930", "앵커", 50.0)])
try:
    build_basket(dup, REG, "2026-12-14", "x")
    check("코드 중복 예외", False)
except ValueError:
    check("코드 중복 예외", True)

alien = comp([("삼성전자", "005930", "앵커", 50.0),
              ("NVIDIA", "NVDA", "핵심", 50.0)])           # 등록부 밖 해외
try:
    build_basket(alien, REG, "2026-12-14", "x")
    check("등록부 밖 해외 티커 예외", False)
except ValueError as e:
    check("등록부 밖 해외 티커 예외", "NVDA" in str(e), str(e)[:60])

neg = comp([("삼성전자", "005930", "앵커", 100.5),
            ("한미반도체", "042700", "핵심", -0.5)])
try:
    build_basket(neg, REG, "2026-12-14", "x")
    check("음수 비중 예외", False)
except ValueError:
    check("음수 비중 예외", True)

try:
    build_basket(GOOD, REG, "시행일아님", "x")
    check("시행일 파싱 예외", False)
except Exception:
    check("시행일 파싱 예외", True)

# ── 3) 원자적 쓰기 — 기존 파일 보존 ───────────────────────────────────
tmp = Path(tempfile.mkdtemp())
target = tmp / "basket.csv"
_atomic_write(target, "v1")
check("쓰기 성공", target.read_text(encoding="utf-8-sig") == "v1")
_atomic_write(target, "v2")
check("교체 성공(잔여 tmp 없음)",
      target.read_text(encoding="utf-8-sig") == "v2"
      and not list(tmp.glob("*.tmp")))
# 검증이 쓰기보다 먼저다 — build_basket 예외 시 파일은 그대로
before = target.read_text(encoding="utf-8-sig")
try:
    build_basket(bad_sum, REG, "2026-12-14", "x")
except ValueError:
    pass
check("검증 실패는 파일을 건드리지 않음",
      target.read_text(encoding="utf-8-sig") == before)

# ── 4) 실제 정본 구성표로 왕복 (읽기 전용) ────────────────────────────
real = pd.read_csv("data/processed/구성표_글로벌확정_20260729.csv",
                   encoding="utf-8-sig")
from etf.global_candidates import normalize_code  # noqa: E402

real["코드"] = real["코드"].map(normalize_code)
rb, rm = build_basket(real, REG, "2026-07-29", "구성표_글로벌확정_20260729.csv")
check("정본 13종목 전부 인계", rm["n_stocks"] == 13, rm["n_stocks"])
check("정본 해외 1종목(MU)", rm["n_foreign"] == 1)
check("정본 비중 합 100", abs(rm["weight_sum_pct"] - 100.0) < 0.5)

print()
print("전부 통과" if ok else "실패 있음")
sys.exit(0 if ok else 1)
