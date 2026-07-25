# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

**정가 HBM ETF** — 팀 프로젝트(HBM_index)에서 만든 HBM 테마 커스텀 인덱스를 기반으로, **나만의 ETF를 설계**하는 개인 확장 프로젝트. 팀 완성본(중간발표 시점, 2026-07-25 스냅샷)을 동결 엔진으로 가져왔고, 그 위에 ETF 상품화 레이어를 얹는다.

- 원본 팀 레포: `D:\dev\HBM_index` (`완성본/` 폴더가 이 레포의 뿌리). **팀 레포와 git 연결 없음** — 팀 쪽이 바뀌어도 여기는 확정본 기준으로 독립 운영.
- Python 3.12 + 레포별 `.venv`. 한글 출력은 `PYTHONUTF8=1`로 실행.

## 자주 쓰는 명령어

```powershell
# 테스트 3종 (전부 오프라인, 합계 33개)
.venv\Scripts\python.exe tests\test_v2.py                   # v2 방법론 명세 9개
.venv\Scripts\python.exe tests\test_schedule_v2.py          # 스케줄러 스모크 16개
.venv\Scripts\python.exe tests\test_develop_integration.py  # 통합 8개

# 버퍼 정책 민감도 분석 (analysis/ 에 CSV 산출)
.venv\Scripts\python.exe analysis\sensitivity_v2.py
```

## 아키텍처

### 동결된 지수 엔진 (팀 완성본 — 원칙적으로 수정하지 않음)

```
src/universe.py → selection.py → weighting.py → index_calc.py
                     (선정)      (40/60+캡→IIF)   (M(t)=ΣIIF×FF×S×P)
src/rebalance.py — v2 방법론: 정원 폐지·히스테리시스 버퍼·무대체 수시변경.
                   비중은 weighting.py에 위임(assign_weights_v2 = 어댑터)
backtest/backtest.py — 이벤트 소비형 백테스트 (rebalance가 이벤트 생산,
                   backtest가 지수 재생. PR/TR 구분 — prices는 배당 미반영 수정주가여야 함)
```

- 현재 구성: 7종목 (앵커 삼성전자·SK하이닉스 40% / 핵심 한미반도체·테크윙·디아이·넥스틴 / 위성 와이씨켐). `data/processed/구성표_실데이터_20260723.csv`
- 방법론 근거 문서: `docs/methodology.md`, 제출 PDF들은 `docs/제출문서/`
- 엔진을 고쳐야 할 땐 팀 레포(`D:\dev\HBM_index`)와의 diff를 의식할 것 — 여긴 스냅샷이다.

### ETF 레이어 (`etf/` — 이 레포의 신규 작업)

지수 → ETF 상품화에 필요한 것들. 계획(2026-07-25 합의):

1. **추적오차 시뮬레이션** (1순위) — 지수수익률 − 운용보수(TER) − 리밸런싱 매매비용·슬리피지 = ETF NAV. 기존 backtest.py 이벤트 구조 재사용. 연 추적오차 bp가 핵심 산출물.
2. **용량(Capacity) 분석** (1순위) — 종목별 (AUM×비중)÷일평균거래대금. 소형주(와이씨켐 0.61%)가 병목 → "AUM 얼마까지 소화 가능" 상한 도출.
3. **CU/PDF 설계** — 설정단위 1CU 기준 종목별 정수 주식수 + 정수화 비중 괴리(bp). IIF에서 환산.
4. **벤치마크 비교** — 기존 반도체 ETF(SOL 소부장, TIGER TOP10 등) 대비 구성 겹침·HBM 순도(노출도 가중) 정량 비교.
5. **분산요건 검토** — 자본시장법 지수형 ETF 분산요건(동일종목 상한) 충족 문서화.

## 알아둘 것

- 백테스트 가격 계약: **배당 미반영 수정주가**(PR). 공급처 수정주가가 TR 기준이면 결과가 부풀려짐 — backtest.py 도크스트링 참조.
- 회전율의 유일한 공식 수치는 `bt["turnover"]` (목표비중 비교는 drift를 놓침).
- `analysis/buffer_policy_sensitivity_v2.csv`: 버퍼 정책별 회전율·비용 드래그 비교 — wide(25%/65%)가 드래그 최소 6.7bp.
- pykrx import 시 "KRX 로그인 실패" 경고는 무해 (KRX_ID/PW 환경변수 없을 때 뜸, 시세 조회는 동작).
- `PR_NOTE.md`·`완성본_안내.md`는 팀 인계 당시 기록 — 역사 자료로 보존.
