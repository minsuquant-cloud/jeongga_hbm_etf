# -*- coding: utf-8 -*-
"""
etf/compliance.py — 지수형 ETF 분산요건 점검 (레이어 5단계)
===========================================================
"이 지수로 ETF를 상장할 수 있는가"를 규정 항목별 PASS/FAIL/WARN으로 점검한다.

점검 근거 (2026-07 확인)
------------------------
[R1] 기초지수 구성종목 10종목 이상 — 유가증권시장 상장규정(패시브 ETF 요건).
[R2] 1종목 최대 비중 30% 이하 — 동 규정. (자본시장법상 지수형 집합투자기구의
     동일종목 특례 상한 30%와 정합)
[R3] (경고) 소수종목 테마형 20% 상한 — 2024-04 거래소 내부방침 보도(서울경제).
     정식 규정화 여부·적용 범위(신규/기존)가 유동적이므로 FAIL이 아닌 WARN으로
     다루되, 신규 상장 심사에서 걸릴 수 있음을 표기한다. 극소수 기업이 주도하는
     산업(예: HBM 양산 2사)은 예외 논의가 있다.
[R4] (내부 정합) 지수 자체 상한(앵커 개별 25%· 핵심 18%·위성 15%·위성합 18%)
     준수 — weighting.verify()가 담당하므로 여기서는 최대비중만 재확인.

판정 원칙: 확인된 규정만 점검한다. 근거가 유동적인 항목은 WARN으로 분리해
"규정처럼 보이는 소문"과 섞지 않는다(fail-closed가 아니라 honest-labeling).
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MIN_CONSTITUENTS = 10        # [R1]
MAX_WEIGHT = 0.30            # [R2]
MAX_WEIGHT_TIGHT = 0.20      # [R3] 강화 방침 (WARN 기준)


def check_diversification(weights: pd.Series) -> pd.DataFrame:
    """구성 비중(합 1)에 대해 분산요건 점검표를 만든다.

    반환: DataFrame[항목, 기준, 실측, 판정(PASS/FAIL/WARN), 비고]
    """
    if len(weights) == 0:
        raise ValueError("비중이 비어 있습니다")
    w = weights / weights.sum()
    if (w < -1e-12).any():
        raise ValueError("음수 비중 — 입력 확인 필요")

    n = int(len(w))
    w_max = float(w.max())
    top = str(w.idxmax())

    rows = [
        {
            "항목": "[R1] 구성종목 수 ≥ 10 (상장규정)",
            "기준": f"≥ {MIN_CONSTITUENTS}",
            "실측": n,
            "판정": "PASS" if n >= MIN_CONSTITUENTS else "FAIL",
            "비고": "" if n >= MIN_CONSTITUENTS else
                    f"{MIN_CONSTITUENTS - n}종목 부족 — 이대로는 상장 불가",
        },
        {
            "항목": "[R2] 1종목 최대 비중 ≤ 30%",
            "기준": f"≤ {MAX_WEIGHT:.0%}",
            "실측": f"{w_max:.2%} ({top})",
            "판정": "PASS" if w_max <= MAX_WEIGHT + 1e-9 else "FAIL",
            "비고": "",
        },
        {
            "항목": "[R3] 소수종목 테마형 20% 상한 (강화 방침)",
            "기준": f"≤ {MAX_WEIGHT_TIGHT:.0%}",
            "실측": f"{w_max:.2%} ({top})",
            "판정": "PASS" if w_max <= MAX_WEIGHT_TIGHT + 1e-9 else "WARN",
            "비고": "" if w_max <= MAX_WEIGHT_TIGHT + 1e-9 else
                    "정식 규정화 여부 유동 — 신규 심사에서 쟁점 가능. "
                    "극소수 기업 주도 산업 예외 논의 있음(HBM 양산 2사 해당 소지)",
        },
    ]
    return pd.DataFrame(rows)


def remediation_notes(weights: pd.Series) -> list[str]:
    """FAIL 항목에 대한 해소 방안 메모 (방법론 개정은 팀 논의 사항)."""
    notes = []
    n = len(weights)
    if n < MIN_CONSTITUENTS:
        notes.append(
            f"종목 수 {n} < {MIN_CONSTITUENTS}: 지수 방법론은 가변 종목수(정원 폐지)라 "
            "자격 기업이 늘면 자연 해소되지만, 상장 요건은 '항상 10 이상'을 요구한다. "
            "선택지: ① 위성군 임계값(메모리향 70%) 완화로 편입 풀 확대 — 순도 희석과 "
            "교환 관계, ② 핵심군 노출도 문턱(30%) 인하 — 동일 교환 관계, "
            "③ '최소 종목수 보장 조항' 신설(문턱 미달 시 차순위 충원) — 팀 방법론 "
            "개정 필요(정원 폐지 취지와의 정합 논의). ④ 지수는 그대로 두고 ETF가 아닌 "
            "지수 산출·공표만 우선(라이선스 모델).")
    w = weights / weights.sum()
    if float(w.max()) > MAX_WEIGHT_TIGHT:
        notes.append(
            f"최대 비중 {float(w.max()):.2%} > 20%: 강화 방침이 정식화되면 앵커 개별 "
            "상한(현 25%)을 20%로 내리는 방법론 개정으로 대응 가능 — 앵커 40% 합계는 "
            "유지되므로 삼성·SK 배분만 재조정된다.")
    return notes
