# -*- coding: utf-8 -*-
"""
etf/export_basket.py — 리밸런싱 확정 구성 → 정가 유니버스 인계 (전량 교체 계약)
==============================================================================
사용자 결정(2026-07-29): 리밸런싱 후 정가(운용 시스템) 유니버스의 HBM_etf
슬롯은 이 바스켓으로 **통째로 교체**한다. 레포 간 직접 import 없이 공용 데이터
루트(D:\\data\\_index)가 인터페이스다 — JGHBM.parquet(지수 시세)와 같은 원칙.

소비자 계약 (정가 쪽이 지켜야 할 것)
------------------------------------
1. **전량 교체는 '목표'의 교체다** — 바스켓 파일이 새로 오면 HBM_etf 슬롯의
   목표 구성을 이 파일로 완전히 갈아끼운다(부분 채택 금지 — 부분 채택은
   비중 합이 깨져 어느 판도 아닌 혼종이 된다).
2. **주문은 diff로 낸다.** 전량 매도 후 재매수는 리밸당 편도 회전율 100%
   (연 2회면 연 200%) — 왕복 30bp 기준 연 60bp 드래그로, 현행 설계의
   drift 되돌림(연 ~27%, 비용 ~8bp)의 7배가 넘는다. 버퍼 정책으로 회전을
   눌러 온 설계(analysis/buffer_policy_sensitivity_v2)를 주문 방식이
   무효화하면 안 된다.
3. **시행 시점**: effective_date 종가부터 유효 (방법론 3장 — 확정·공표 후
   정기변경일 종가 적용). 그 전에 미리 매매하지 않는다.
4. **무결성 검사 후 교체**: meta의 sha256과 바스켓 파일 해시가 다르거나,
   비중 합이 100±0.5%를 벗어나거나, effective_date가 파싱 불가면 교체하지
   않고 직전 바스켓을 유지한다(fail-closed — 깨진 파일로 갈아타지 않는다).
5. 해외 종목(통화 ≠ KRW)은 거래소·통화 컬럼으로 식별한다. 해외 주문을
   지원하지 않는 실행 환경이면 **바스켓 전체를 거부**한다 — MU만 빼고
   사는 것은 부분 채택이다(1번 위반).

산출 원칙 (이 레포 쪽)
----------------------
- 검증 실패 시 기존 파일을 건드리지 않는다(직전 정상본 보존).
- 쓰기는 원자적(tmp → os.replace) — 소비자가 쓰다 만 파일을 읽지 않게.
- 구성 출처는 단일 진입점(run_tracking.load_constituents) — 정본이 바뀌면
  여기도 자동으로 따라온다.

사용:
    .venv/Scripts/python.exe etf/export_basket.py [--effective 2026-12-14]
    (--effective 생략 시 오늘 — 정기변경 인계 때는 정기변경일을 명시할 것)
산출: D:\\data\\_index\\JGHBM_basket.csv + JGHBM_basket_meta.csv
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.global_candidates import registry  # noqa: E402

TICKER = "JGHBM"
OUT_DIR = Path(r"D:/data/_index")
SCHEMA_VERSION = 1

BASKET_COLS = ["코드", "종목명", "군", "목표비중(%)", "통화", "거래소"]


def build_basket(comp: pd.DataFrame, reg: pd.DataFrame,
                 effective_date: str, source: str) -> tuple[pd.DataFrame, pd.Series]:
    """구성표 → 인계 바스켓 + 메타. 순수 함수(오프라인 테스트 대상).

    fail-closed 검증:
      · 비중 합 100±0.5% / 비중 ≤ 0 금지 / 코드 중복 금지
      · 해외 티커(비숫자 코드)는 등록부에 있어야 통화·거래소를 안다 —
        없으면 예외. 조용히 KRW로 두면 정가가 해외 주문을 원화 주문으로 낸다.
      · effective_date는 ISO 날짜여야 한다
    """
    eff = pd.Timestamp(effective_date)          # 파싱 실패 시 여기서 예외
    d = comp.copy()
    need = {"코드", "종목명", "군", "편입비중(%)"}
    missing = need - set(d.columns)
    if missing:
        raise ValueError(f"구성표 컬럼 누락: {sorted(missing)}")
    if d["코드"].duplicated().any():
        raise ValueError(f"코드 중복: {d.loc[d['코드'].duplicated(), '코드'].tolist()}")
    w = pd.to_numeric(d["편입비중(%)"], errors="coerce")
    if w.isna().any() or (w <= 0).any():
        raise ValueError("비중이 결측/0 이하인 행이 있음")
    if abs(float(w.sum()) - 100.0) > 0.5:
        raise ValueError(f"비중 합 {w.sum():.2f}% ≠ 100%")

    reg_map = reg.set_index("코드")
    cur, exch = [], []
    for code in d["코드"]:
        if str(code).isdigit():
            cur.append("KRW")
            exch.append("KRX")
        elif code in reg_map.index:
            cur.append(reg_map.at[code, "통화"])
            exch.append(reg_map.at[code, "거래소"])
        else:
            raise ValueError(
                f"해외 티커 {code}가 등록부에 없음 — 통화·거래소를 모른 채 "
                "인계하면 정가가 원화 주문을 낸다(fail-closed)")

    basket = pd.DataFrame({
        "코드": d["코드"].values, "종목명": d["종목명"].values,
        "군": d["군"].values, "목표비중(%)": w.round(4).values,
        "통화": cur, "거래소": exch,
    })[BASKET_COLS]

    csv_bytes = basket.to_csv(index=False).encode("utf-8-sig")
    meta = pd.Series({
        "ticker": TICKER,
        "schema_version": SCHEMA_VERSION,
        "swap_mode": "full_replace",            # 부분 채택 금지 — 도크스트링 계약
        "effective_date": str(eff.date()),      # 이 날 종가부터 유효
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": source,
        "n_stocks": len(basket),
        "n_foreign": int((basket["통화"] != "KRW").sum()),
        "weight_sum_pct": round(float(w.sum()), 4),
        "sha256": hashlib.sha256(csv_bytes).hexdigest(),
    })
    return basket, meta


def _atomic_write(path: Path, text: str) -> None:
    """tmp에 쓴 뒤 교체 — 소비자가 쓰다 만 파일을 읽는 사고 방지."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8-sig")
    os.replace(tmp, path)


def export(effective_date: str | None = None) -> Path:
    from etf.run_tracking import load_constituents, source_line
    comp = load_constituents()                  # 단일 진입점 — 정본 자동 추종
    eff = effective_date or str(dt.date.today())
    basket, meta = build_basket(comp, registry(), eff,
                                source=comp.attrs.get("source", "?"))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write(OUT_DIR / f"{TICKER}_basket.csv", basket.to_csv(index=False))
    _atomic_write(OUT_DIR / f"{TICKER}_basket_meta.csv",
                  meta.to_csv(header=False))

    print(f"[바스켓 인계] {source_line(comp)} → {OUT_DIR / f'{TICKER}_basket.csv'}")
    print(f"  시행일 {meta['effective_date']} 종가부터 · 전량 교체(full_replace) · "
          f"해외 {meta['n_foreign']}종목 포함")
    print(basket.to_string(index=False))
    print("\n계약 요약: 목표는 통째 교체, 주문은 diff — 전량 매도·재매수는 "
          "연 60bp급 드래그(도크스트링 2항).")
    return OUT_DIR / f"{TICKER}_basket.csv"


def main() -> int:
    ap = argparse.ArgumentParser(description="확정 구성 → 정가 유니버스 인계")
    ap.add_argument("--effective", default=None,
                    help="시행일(YYYY-MM-DD, 이 날 종가부터 유효). 생략 시 오늘")
    args = ap.parse_args()
    export(args.effective)
    return 0


if __name__ == "__main__":
    sys.exit(main())
