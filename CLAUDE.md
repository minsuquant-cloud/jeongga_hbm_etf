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

### ETF 레이어 (`etf/` — 이 레포의 신규 작업, 5단계 전부 완료 2026-07-25)

모듈은 전부 "순수 로직(테스트 대상) + run_*.py(실데이터 러너)" 쌍. 산출 CSV는 `etf/output/`.

1. ✅ **추적오차** (`nav_sim.py` / `run_tracking.py`) — bt(level·turnover)에서 NAV 재생. TER은 달력일 일할, 드래그는 로그 항등 분해(합계=실측). 실측: TER45+비용30 = 갭 61bp/년, **현금 1%만으로 92bp** — 초강세 테마라 현금관리 > 보수.
2. ✅ **용량** (`capacity.py` / `run_capacity.py`) — 용량 = min(허용일수×참여율×ADV/비중). 실측: **613억 원**, 병목은 와이씨켐(꼬마 비중)이 아니라 **넥스틴**(비중 10.6%×ADV 65억).
3. ✅ **CU/PDF** (`cu_design.py` / `run_cu.py`) — floor+현금(현금 ≥0 불변식), 0주 종목 검출. 실측: **권장 CU 5억**(총괴리 8.3bp), 정밀도 병목은 **SK하이닉스 주가 176만원**(52주 → -13.6bp).
4. ✅ **벤치마크 비교** (`benchmark.py` / `run_benchmark.py`) — 경쟁 ETF 실보유(KRX PDF, `.env` KRX_ID/PW 필요)에 판정 33종목 노출도 적용. 실측: **우리 순도 35.6% vs 국내 경쟁 11.8~22.3% = 1.6~3.0배** (국내주 HBM 상품은 사실상 유일 — PLUS 글로벌HBM은 해외형).
5. ✅ **분산요건** (`compliance.py` / `run_compliance.py`) — **[핵심 제약] 현 구성 7종목 < 상장규정 최소 10종목 → 이대로는 ETF 상장 불가.** 최대비중 21.57%는 30% 규정 PASS, 20% 강화방침엔 WARN. 해소 방안 4종은 remediation_notes 참조(방법론 개정 = 팀 논의 사항).

6. ✅ **종목수 10 시나리오** (`scenario_min10.py` / `run_scenario_min10.py`) — 팀 엔진(selection→weighting)을 임계값 컨텍스트로 재실행. **위성 임계 완화 단독은 무효**(공정·위원회 확인 통과가 현 7종목뿐 — 걸림돌은 실사 문서). 핵심 문턱 5%까지 내려야 12종목(순도 27.1%로 최저·규칙 정체성 훼손) vs **★S4 실사 확대(문턱 유지): 14종목 PASS·순도 28.8%** — 위성 상한 18%가 희석을 통제. S4여도 경쟁 ETF 순도(11.8~22.3%)보다 높아 "국내 1위" 유지.

다음 후보 작업: 투자설명서 증보판(위 6개 숫자 반영), S4 구성으로 용량·CU 재산출(종목 늘면 용량 개선 예상), 상승/하락장별 추적오차 스트레스.

## 알아둘 것

- 백테스트 가격 계약: **배당 미반영 수정주가**(PR). 공급처 수정주가가 TR 기준이면 결과가 부풀려짐 — backtest.py 도크스트링 참조.
- 회전율의 유일한 공식 수치는 `bt["turnover"]` (목표비중 비교는 drift를 놓침).
- `analysis/buffer_policy_sensitivity_v2.csv`: 버퍼 정책별 회전율·비용 드래그 비교 — wide(25%/65%)가 드래그 최소 6.7bp.
- pykrx import 시 "KRX 로그인 실패" 경고는 무해 (KRX_ID/PW 환경변수 없을 때 뜸, 시세 조회는 동작).
- `PR_NOTE.md`·`완성본_안내.md`는 팀 인계 당시 기록 — 역사 자료로 보존.
