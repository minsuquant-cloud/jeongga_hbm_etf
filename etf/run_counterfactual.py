# -*- coding: utf-8 -*-
"""
etf/run_counterfactual.py — 동일가중 반사실: 수익률 주장의 상한선

12.5년 백테스트의 수익률에는 사후선택이 세 겹 실려 있다.
  ① 종목: 2026년 HBM 판정을 통과한 기업만 담았다 (생존 편향 — 같은 시기에
     사라진 소부장 기업은 애초에 후보에 없다)
  ② 비중: 오늘의 유동시총 비중 = '이미 오른 종목'에 큰 비중을 소급 배정
  ③ 시점: 상장 후 첫 분기 재고정에 바로 편입 (실제 규칙이면 실사를 거친다)

이 중 ②의 크기는 잴 수 있다 — **같은 12종목, 같은 재고정 규칙에서 비중만
동일가중으로** 바꿔 다시 돌린다. 두 지수의 수익률 차이가 '오늘 비중을 소급한
프리미엄'이고, 우리 수익률 주장이 넘어서는 안 되는 상한선 노릇을 한다.

반대로 낙폭(MDD)이 두 지수에서 비슷하면, 낙폭은 비중 선택에 강건한 —
믿어도 되는 — 숫자라는 뜻이다. 이 리포트의 목적은 수익률을 자랑하는 게
아니라 **어느 숫자를 믿어도 되는지 가르는 것**이다.

    .venv/Scripts/python.exe etf/run_counterfactual.py

산출: etf/output/counterfactual.csv
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etf.hist_data import build_index, load_composition  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "etf", "output")

PERIODS = [
    ("2014-01-02", "2019-12-31", "2014~2019 (테마 이전)"),
    ("2020-01-02", "2023-12-31", "2020~2023 (테마 형성)"),
    ("2024-01-02", None, "2024~현재 (슈퍼사이클)"),
    ("2014-01-02", None, "전체 12.5년"),
]


def _ret_mdd(level: pd.Series, a: str, b: str | None) -> tuple[float, float]:
    s = level.loc[a:b] if b else level.loc[a:]
    ret = float(s.iloc[-1] / s.iloc[0] - 1) * 100
    mdd = float((s / s.cummax() - 1).min()) * 100
    return ret, mdd


def main() -> int:
    target = load_composition()
    equal = pd.Series(1.0, index=target.index)      # 동일가중 (내부 정규화)

    bt_w = build_index()                            # 오늘의 비중
    bt_e = build_index(target=equal)                # 동일가중 반사실

    rows = []
    for a, b, label in PERIODS:
        rw, mw = _ret_mdd(bt_w["level"], a, b)
        re_, me = _ret_mdd(bt_e["level"], a, b)
        rows.append({"구간": label,
                     "오늘비중 수익률(%)": round(rw, 1),
                     "동일가중 수익률(%)": round(re_, 1),
                     "차이(%p)": round(rw - re_, 1),
                     "오늘비중 MDD(%)": round(mw, 1),
                     "동일가중 MDD(%)": round(me, 1)})
    df = pd.DataFrame(rows)

    end = bt_w.index[-1].date()
    print(f"[동일가중 반사실] 같은 12종목 · 같은 분기 재고정 · 비중만 교체 "
          f"(~{end})\n")
    print(df.to_string(index=False))

    full = df.iloc[-1]
    print(f"\n읽는 법:")
    print(f"  · 차이 {full['차이(%p)']:+,.0f}%p = 오늘의 비중을 소급한 프리미엄. "
          "수익률 주장에는 이만큼의 사후선택이 실려 있다.")
    print(f"  · MDD는 {full['오늘비중 MDD(%)']:.0f}% vs {full['동일가중 MDD(%)']:.0f}% — "
          "어느 비중이든 -45% 이상 깨진다. 낙폭은 비중 선택의 산물이 아니라 "
          "구간의 실체다(오늘 비중이 오히려 낙폭을 완화해 보이게 하는 쪽). "
          "낙폭·용량·드래그가 믿어도 되는 숫자다.")
    print("  · 종목 선택(생존 편향)·편입 시점의 사후성은 이 표로도 못 잰다 — "
          "수익률은 어떤 형태로든 성과 주장에 쓰지 않는다.")

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "counterfactual.csv")
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n저장: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
