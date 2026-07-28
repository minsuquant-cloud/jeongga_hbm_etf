# -*- coding: utf-8 -*-
"""
etf/run_health.py — 편입 12종목 + 관찰종목 재무·거래 건강 경보

왜 필요한가 (2026-07-28)
------------------------
실사는 2026-07-25에 끝났지만 기업은 그 뒤로도 계속 변한다. 상폐 부검(quant_lab
run_delisting_screen)이 확정한 죽음의 선행 신호 — 완전자본잠식(폭락형 소멸의 30%
vs 생존 2%), 4분기 연속 영업적자(41% vs 19%), 저가주화·거래정지 — 를 편입·관찰
종목에 상시 적용한다. 경보가 뜨면 수시변경(rebalance_v2) 검토 대상.

    .venv/Scripts/python.exe etf/run_health.py

산출: etf/output/health_report.csv (경보 있으면 exit 1)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.hist_data import load_composition  # noqa: E402

_SNAP = Path(r"D:/data/_derived")
OUT = Path(__file__).resolve().parent / "output"

# 관찰종목 (2026-07-25 실사 판정: 편입 보류 — 공시·실적 모니터링 대상)
WATCH = {"222800": "심텍", "056190": "에스에프에이"}


def _fin_panel() -> dict[str, pd.DataFrame]:
    fin = pd.read_parquet(_SNAP / "fin_quarterly.parquet")
    fin["code6"] = fin["코드"].astype(str).str.replace("A", "", regex=False).str.zfill(6)
    qcols = [c for c in fin.columns if str(c)[:2] == "20"][:-1]   # 빈 마지막 컬럼 제외
    out = {}
    for item in ("자본총계(천원)", "영업이익(천원)", "부채총계(천원)"):
        out[item] = fin[fin["아이템명"] == item].set_index("code6")[qcols].astype(float)
    return out


def main() -> int:
    comp = load_composition()
    # 전 종목 이름 사전 (구성표 밖 관찰종목까지 조회 가능해야 함)
    names = (pd.read_parquet(_SNAP / "code_name.parquet")
             .set_index("Code")["Name"])
    codes = {c: str(names.get(c, c)) for c in comp.index} | WATCH

    # 관찰종목 이름 대조 — 코드 오타가 조용히 엉뚱한 회사를 감시하는 사고 방지
    for c, expected in WATCH.items():
        actual = str(names.get(c, "?"))
        if expected[:2] not in actual:
            print(f"⚠ 관찰종목 코드 확인 필요: {c} 기대 '{expected}' vs 데이터 '{actual}'")

    fin = _fin_panel()
    raw = pd.read_parquet(_SNAP.parent / "_live" / "price_close.parquet")
    vol = pd.read_parquet(_SNAP.parent / "_live" / "price_volume.parquet")
    adj = pd.read_parquet(_SNAP.parent / "_live" / "price_adj_close.parquet")

    rows = []
    for c, name in codes.items():
        role = "관찰" if c in WATCH else "편입"
        eq = fin["자본총계(천원)"].loc[c].dropna() if c in fin["자본총계(천원)"].index else pd.Series(dtype=float)
        op = fin["영업이익(천원)"].loc[c].dropna() if c in fin["영업이익(천원)"].index else pd.Series(dtype=float)
        li = fin["부채총계(천원)"].loc[c].dropna() if c in fin["부채총계(천원)"].index else pd.Series(dtype=float)

        impaired = bool(len(eq) and eq.iloc[-1] <= 0)
        loss4 = bool(len(op) >= 4 and (op.iloc[-4:] < 0).all())
        debt_ratio = float(li.iloc[-1] / eq.iloc[-1] * 100) if len(eq) and len(li) and eq.iloc[-1] > 0 else float("nan")
        last_raw = float(raw[c].dropna().iloc[-1]) if c in raw.columns else float("nan")
        halt = float((((vol[c] == 0) | vol[c].isna()) & adj[c].notna()).iloc[-250:].mean()) if c in vol.columns else float("nan")

        alerts = []
        if impaired:
            alerts.append("⛔완전자본잠식")
        if loss4:
            alerts.append("⛔4분기연속적자")
        if last_raw < 1000:
            alerts.append("⛔저가주")
        if halt > 0.10:
            alerts.append("⛔거래정지경험")
        if debt_ratio > 300:
            alerts.append("⚠부채비율300%+")

        rows.append({"코드": c, "종목명": name, "구분": role,
                     "최근분기": str(eq.index[-1])[:10] if len(eq) else "-",
                     "자본총계(억)": round(eq.iloc[-1] / 1e5) if len(eq) else None,
                     "부채비율(%)": round(debt_ratio) if debt_ratio == debt_ratio else None,
                     "영업이익_최근4Q적자수": int((op.iloc[-4:] < 0).sum()) if len(op) >= 4 else None,
                     "무거래일비중": round(halt, 3) if halt == halt else None,
                     "경보": " ".join(alerts) or "✅"})

    df = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "health_report.csv", index=False, encoding="utf-8-sig")

    print(f"편입 {len(comp)} + 관찰 {len(WATCH)}종목 건강 점검 "
          f"(재무 최근분기 + 가격 _live 오늘까지)\n")
    print(df.to_string(index=False))
    n_bad = df["경보"].str.contains("⛔").sum()
    print(f"\n{'⛔ 경보 ' + str(n_bad) + '건 — 수시변경 검토' if n_bad else '✅ 전 종목 이상 없음'}"
          f"  |  저장: output/health_report.csv")
    return 1 if n_bad else 0


if __name__ == "__main__":
    sys.exit(main())
