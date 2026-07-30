# -*- coding: utf-8 -*-
"""정가 HBM ETF 설계서 (교육용 모의 문서) — 증보판 PDF.

팀 투자설명서(HBM지수_투자설명서.pdf)의 후속편: 지수 → ETF 상품화 검증
6단계(추적오차·용량·CU·순도비교·분산요건·실사확정)의 실측 숫자를 담는다.
스타일은 팀 문서(네이비·골드, 훅 스토리텔링)를 계승.

실행:  .venv/Scripts/python.exe etf/make_pdf_etf.py
출력:  docs/정가HBM_ETF_설계서.pdf
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, NextPageTemplate,
                                PageBreak, PageTemplate, Paragraph, Spacer,
                                Table, TableStyle)

OUT = Path(__file__).resolve().parent.parent / "docs" / "정가HBM_ETF_설계서.pdf"
OUT.parent.mkdir(exist_ok=True)

pdfmetrics.registerFont(TTFont("Kor", r"C:\Windows\Fonts\malgun.ttf"))
pdfmetrics.registerFont(TTFont("KorB", r"C:\Windows\Fonts\malgunbd.ttf"))

NAVY = colors.HexColor("#12213F")
GOLD = colors.HexColor("#C9A227")
INK = colors.HexColor("#1A1A1A")
GRAY = colors.HexColor("#666666")
LINE = colors.HexColor("#C9D2E0")
LIGHT = colors.HexColor("#F2F5FA")
GREEN = colors.HexColor("#1E7B45")
RED = colors.HexColor("#B3261E")
AMBER = colors.HexColor("#B4530A")
BARBG = colors.HexColor("#E3E9F2")


def st(name, size, bold=False, color=INK, leading=None, sa=5, align=0):
    s = ParagraphStyle(name, fontName="KorB" if bold else "Kor", fontSize=size,
                       leading=leading or size * 1.55, textColor=color, spaceAfter=sa)
    s.alignment = align
    return s


H1 = st("h1", 17, bold=True, color=NAVY, sa=3)
KICK = st("kick", 10.5, bold=True, color=AMBER, sa=2)
BODY = st("body", 10.2, sa=6)
BIG = st("big", 13, bold=True, color=NAVY, sa=6, leading=21)
CELL = st("cell", 8.8, leading=13, sa=0)
CELLB = st("cellb", 8.8, bold=True, leading=13, sa=0)
CELLC = st("cellc", 8.8, leading=13, sa=0, align=1)
CELLBC = st("cellbc", 8.8, bold=True, leading=13, sa=0, align=1)
SMALL = st("small", 8.2, color=GRAY, sa=3)
CV_TOP = st("cvtop", 11, bold=True, color=GOLD, sa=6)
CV_HOOK = st("cvhook", 24, bold=True, color=colors.white, leading=38, sa=14)
CV_SUB = st("cvsub", 12.5, color=colors.HexColor("#C8D4E8"), leading=21, sa=8)
CV_NAME = st("cvname", 15, bold=True, color=colors.white, sa=4)
CV_META = st("cvmeta", 9.3, color=colors.HexColor("#8FA3C4"), leading=15, sa=2)


def box(items, bg=LIGHT, border=LINE, title=None, title_bg=NAVY):
    rows = []
    style = [("BOX", (0, 0), (-1, -1), 0.8, border),
             ("TOPPADDING", (0, 0), (-1, -1), 5),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
             ("LEFTPADDING", (0, 0), (-1, -1), 10),
             ("RIGHTPADDING", (0, 0), (-1, -1), 10)]
    if title:
        rows.append([Paragraph(title, st("bt", 10, bold=True, color=colors.white, sa=1))])
        style += [("BACKGROUND", (0, 0), (-1, 0), title_bg),
                  ("BACKGROUND", (0, 1), (-1, -1), bg),
                  ("TOPPADDING", (0, 0), (-1, 0), 6),
                  ("BOTTOMPADDING", (0, 0), (-1, 0), 6)]
    else:
        style.append(("BACKGROUND", (0, 0), (-1, -1), bg))
    rows += [[Paragraph(t, s)] for s, t in items]
    t = Table(rows, colWidths=[178 * mm])
    t.setStyle(TableStyle(style))
    return t


def weight_bar(pct, maxpct=25.0, width=44 * mm, color=NAVY):
    filled = max(1.2 * mm, width * min(pct / maxpct, 1.0))
    bar = Table([["", ""]], colWidths=[filled, width - filled], rowHeights=[4.0 * mm])
    bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), color),
                             ("BACKGROUND", (1, 0), (1, 0), BARBG)]))
    return bar


def grid(header, rows, widths, aligns=None):
    data = [[Paragraph(h, st("gh", 8.6, bold=True, color=colors.white, sa=0,
                             align=1)) for h in header]]
    for r in rows:
        data.append([c if not isinstance(c, str) else Paragraph(c, CELL) for c in r])
    t = Table(data, colWidths=widths)
    style = [("BACKGROUND", (0, 0), (-1, 0), NAVY),
             ("GRID", (0, 0), (-1, -1), 0.5, LINE),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("TOPPADDING", (0, 0), (-1, -1), 4),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
             ("LEFTPADDING", (0, 0), (-1, -1), 6),
             ("RIGHTPADDING", (0, 0), (-1, -1), 6),
             ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT])]
    t.setStyle(TableStyle(style))
    return t


doc = BaseDocTemplate(str(OUT), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                      topMargin=15 * mm, bottomMargin=16 * mm)
W = doc.width


def cover_bg(canvas, _doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(2)
    canvas.line(16 * mm, 40 * mm, 70 * mm, 40 * mm)
    canvas.restoreState()


def body_page(canvas, _doc):
    canvas.saveState()
    canvas.setFont("Kor", 7.6)
    canvas.setFillColor(GRAY)
    canvas.drawString(16 * mm, 9 * mm, "정가 HBM ETF 설계서 (교육용 모의 문서)")
    canvas.drawRightString(16 * mm + W, 9 * mm, f"- {canvas.getPageNumber()} -")
    canvas.restoreState()


doc.addPageTemplates([
    PageTemplate(id="cover", frames=[Frame(16 * mm, 16 * mm, W, A4[1] - 32 * mm)],
                 onPage=cover_bg),
    PageTemplate(id="body", frames=[Frame(16 * mm, 16 * mm, W, A4[1] - 31 * mm)],
                 onPage=body_page),
])

E = []
A = E.append

# ═══════════════ 표지 ═══════════════
A(Spacer(1, 28 * mm))
A(Paragraph("교육용 모의 설계서 · 개인 확장 프로젝트 (팀 지수의 후속편)", CV_TOP))
A(Spacer(1, 6 * mm))
A(Paragraph("지수는 완성됐습니다.<br/>이제 '살 수 있는 것'이 될 차례입니다.", CV_HOOK))
A(Paragraph("지수와 ETF 사이에는 다섯 개의 관문이 있습니다 — 추적오차, 유동성 용량,<br/>"
            "설정단위 설계, 경쟁 상품 대비 존재 이유, 그리고 상장 규정.<br/>"
            "이 문서는 다섯 관문을 <b><font color='#C9A227'>전부 실측 데이터로 통과</font></b>시킨 기록입니다.", CV_SUB))
A(Spacer(1, 34 * mm))
A(Paragraph("정가 HBM ETF 설계서", CV_NAME))
A(Paragraph("기초지수: HBM 밸류체인 커스텀 인덱스 (팀 완성본 v2 + S6 글로벌 확장)", CV_META))
A(Paragraph("작성 2026-07-25 · 개정 2026-07-29 (글로벌 13종목 단일 정본) · 모든 수치는 재현 가능한 코드로 산출", CV_META))
A(Paragraph("본 문서는 학습 목적의 모의 설계서이며 투자 권유가 아닙니다.", CV_META))
A(NextPageTemplate("body"))
A(PageBreak())

# ═══════════════ 1. 한눈 요약 ═══════════════
A(Paragraph("한눈 요약", KICK))
A(Paragraph("다섯 관문, 다섯 숫자", H1))
A(Spacer(1, 3 * mm))
A(grid(["관문", "질문", "실측 결과", "판정"],
       [["① 추적오차", "지수를 얼마나 따라가나",
         "연 갭 53bp (TER45+비용8) · 현금 1%=24bp",
         Paragraph("<font color='#1E7B45'><b>설계원칙 도출</b></font>", CELLC)],
        ["② 용량", "AUM 얼마까지 소화하나",
         "1,741억 원 (정규장 거래대금 기준, 병목 넥스틴)",
         Paragraph("<font color='#1E7B45'><b>충분</b></font>", CELLC)],
        ["③ CU 설계", "설정단위 정수화 괴리는",
         "1CU=30억 · 총괴리 8.4bp · 가격 교란에도 15bp 이내",
         Paragraph("<font color='#1E7B45'><b>정밀</b></font>", CELLC)],
        ["④ 존재 이유", "기존 ETF와 뭐가 다른가",
         "HBM 순도 29.8% — 국내 경쟁 11.8~22.3% · 양산 3사 완결",
         Paragraph("<font color='#1E7B45'><b>유일 컨셉</b></font>", CELLC)],
        ["⑤ 상장 규정", "규정상 상장 가능한가",
         "13종목·최대 18.0% — 강화 방침(20%)까지 전부 충족",
         Paragraph("<font color='#1E7B45'><b>PASS</b></font>", CELLC)]],
       [24 * mm, 40 * mm, 84 * mm, 30 * mm]))
A(Spacer(1, 4 * mm))
A(box([(BODY, "이 다섯 숫자의 공통점: <b>전부 실제 데이터로 계산했고, 코드와 테스트"
              "(19종 343건)로 재현된다.</b> 희망 섞인 추정이 아니라 지금 시장 기준의 실측이다."),
       (SMALL, "①②③ 2026-07-29 기준(융합 12.5년 + 해외 KRW 환산 · 거래대금 60거래일) · "
               "④ 경쟁사 보유내역 2026-07-24 공시분 · "
               "⑤ 유가증권시장 상장규정(구성종목 ≥10 · 1종목 ≤30%)")]))
A(Spacer(1, 5 * mm))
A(Paragraph("가장 먼저 발견한 것 — 그리고 고친 것", BIG))
A(Paragraph("최초 지수 구성은 7종목이었다. 상장규정의 최소 구성종목(10)에 미달 — "
            "<b>이대로는 ETF가 될 수 없었다.</b> 해소 경로를 6개 시나리오로 정량 비교한 결과, "
            "규칙(핵심군 노출도 30%)을 허무는 대신 <b>위성군 실사를 확대</b>하는 길을 택했다. "
            "그 실사가 이 문서의 4장이다.", BODY))
A(PageBreak())

# ═══════════════ 2. 존재 이유 (순도) ═══════════════
A(Paragraph("왜 이 ETF인가", KICK))
A(Paragraph("국내에서 가장 'HBM다운' 포트폴리오", H1))
A(Paragraph("같은 잣대(자체 판정 33종목의 HBM 노출도)를 경쟁 ETF의 실제 보유내역(KRX 공시 PDF, "
            "2026-07-24)에 적용해 비교했다. 순도 = Σ 보유비중 × HBM 노출도.", BODY))
A(Spacer(1, 2 * mm))
A(grid(["상품", "HBM 순도(하한)", "구성 겹침", "1년 수익률", "비고"],
       [[Paragraph("<b>정가 HBM 지수 (자체)</b>", CELLB),
         Paragraph("<b>29.8%</b>", CELLBC), "—",
         Paragraph("+243%*", CELLC), "13종목 · HBM 양산 3사 완결 · 판정 커버 100%"],
        ["KODEX 반도체", Paragraph("22.3%", CELLC), Paragraph("50%", CELLC),
         Paragraph("+228%", CELLC), "광의 반도체 36종목"],
        ["TIGER 반도체", Paragraph("20.6%", CELLC), Paragraph("50%", CELLC),
         Paragraph("+233%", CELLC), "광의 반도체"],
        ["TIGER 반도체TOP10", Paragraph("16.8%", CELLC), Paragraph("49%", CELLC),
         Paragraph("+193%", CELLC), "대형 집중"],
        ["KODEX AI반도체핵심장비", Paragraph("14.0%", CELLC), Paragraph("32%", CELLC),
         Paragraph("+103%", CELLC), "장비 테마"],
        ["SOL AI반도체소부장", Paragraph("11.8%", CELLC), Paragraph("31%", CELLC),
         Paragraph("+75%", CELLC), "소부장 테마"],
        ["PLUS 글로벌HBM반도체", Paragraph("산출불가", CELLC), "—",
         Paragraph("+423%", CELLC), "해외주 전용(국내주 0)"]],
       [46 * mm, 30 * mm, 22 * mm, 26 * mm, 54 * mm]))
A(Spacer(1, 3 * mm))
A(box([(BODY, "이름에 'HBM'을 단 유일한 기존 상품은 <b>국내 주식을 한 주도 담지 않고</b>, "
              "국내 상품들은 해외 양산사를 못 담는다. <b>HBM 양산 3사(삼성·하이닉스·마이크론) + "
              "국내 공급망을 한 지수에 담은 상품은 이 지수가 유일한 컨셉이다</b> — "
              "글로벌 후보 8종을 같은 규칙으로 실사해 자격자(MU)만 편입한 결과다."),
       (SMALL, "순도 하한 = 비판정 종목(해외주 등)을 0으로 치는 보수적 값. 같은 잣대의 상대 비교로만 해석. "
               "수익률·상관은 2025-07~2026-07, 상관계수 0.84~0.96. "
               "* 자체 수익률은 <b>오늘 확정한 13종목을 1년 소급 재생</b>한 값(사후선택)이고 경쟁 ETF는 "
               "실제 거래된 수익률이다 — 잣대가 다르므로 순도·겹침만 동일 비교로 읽을 것.")]))
A(PageBreak())

# ═══════════════ 3. 최종 구성 ═══════════════
A(Paragraph("무엇을 담는가", KICK))
A(Paragraph("최종 구성 13종목 — 앵커 40 / 핵심 42 / 위성 18", H1))
comp = [
    ("삼성전자", "앵커", 14.54), ("Micron (MU)", "앵커", 13.04),
    ("SK하이닉스", "앵커", 12.42),
    ("한미반도체", "핵심", 18.00), ("테크윙", "핵심", 16.82),
    ("디아이", "핵심", 3.93), ("넥스틴", "핵심", 3.25),
    ("주성엔지니어링", "위성", 13.42), ("솔브레인", "위성", 3.26),
    ("네오셈", "위성", 0.47), ("티이엠씨", "위성", 0.36),
    ("와이씨켐", "위성", 0.30), ("오로스테크놀로지", "위성", 0.19),
]
gcolor = {"앵커": NAVY, "핵심": AMBER, "위성": GREEN}
rows = []
for name, grp, pct in comp:
    rows.append([Paragraph(f"<b>{name}</b>", CELL),
                 Paragraph(grp, st(f"g{name}", 8.8, bold=True, sa=0,
                                   color=gcolor[grp], align=1)),
                 weight_bar(pct, color=gcolor[grp]),
                 Paragraph(f"{pct:.2f}%", CELLBC)])
A(grid(["종목", "군", "비중", "%"], rows,
       [52 * mm, 18 * mm, 48 * mm, 22 * mm]))
A(Spacer(1, 3 * mm))
A(box([(BODY, "비중은 규칙이 정한다: 앵커 40% 고정(개별 25% 상한) + 비앵커 60% 유동시총 "
              "비례(핵심 개별 18%·위성 개별 15%·위성 합계 18% 상한, 수렴 재배분). "
              "위성 합계는 정확히 상한 18%에 닿아 있다 — 저노출 종목의 순도 희석을 "
              "규칙이 자동으로 막는 구조다."),
       (SMALL, "구성 확정일 2026-07-29 (S6 글로벌 확장 — MU 앵커 편입, 40%를 3사 유동시총 비례 재배분. "
               "비앵커 10종 비중은 국내판과 동일 — 40/60 버킷 분리의 기계적 귀결) · "
               "비중 산정 근거: 팀 방법론 v2 (weighting.verify 자동 점검 통과)")]))
A(PageBreak())

# ═══════════════ 4. 실사 이야기 ═══════════════
A(Paragraph("어떻게 13종목이 됐나", KICK))
A(Paragraph("규칙을 지키는 실사 — 국내 편입 5 · 보류 2, 글로벌 편입 1 · 보류 1", H1))
A(Paragraph("위성군 요건은 세 가지다: 메모리향 매출 ≥70% + <b>HBM 고유공정 귀속 매출의 문서 확인</b> "
            "+ 위원회 확인. 후보 7개 기업의 사업보고서를 자동 발췌 도구(hbm_evidence)로 "
            "카드화해 하나씩 판정했다.", BODY))
A(Spacer(1, 2 * mm))
A(grid(["기업", "사업보고서 'HBM'", "판정", "근거 한 줄"],
       [["네오셈", Paragraph("19회 · 수주 10건", CELLC),
         Paragraph("<font color='#1E7B45'><b>편입</b></font>", CELLC),
         "HBM 검사장비 — 언급·수주 모두 풍부"],
        ["티이엠씨", Paragraph("6회", CELLC),
         Paragraph("<font color='#1E7B45'><b>편입</b></font>", CELLC),
         "특수가스 — HBM 공정 사용 명시"],
        ["솔브레인", Paragraph("3회", CELLC),
         Paragraph("<font color='#1E7B45'><b>편입</b></font>", CELLC),
         "소재 — HBM 관련 매출 언급 확인"],
        ["주성엔지니어링", Paragraph("2회 · 수주 1건", CELLC),
         Paragraph("<font color='#1E7B45'><b>편입</b></font>", CELLC),
         "증착 장비 — 메모리향 70% + HBM 언급"],
        ["오로스테크놀로지", Paragraph("0회", CELLC),
         Paragraph("<font color='#1E7B45'><b>편입</b></font>", CELLC),
         "'HBM' 단어는 없지만 <b>TSV Overlay 솔루션</b> 명시 — 고유공정 근거 인정"],
        ["심텍", Paragraph("0회", CELLC),
         Paragraph("<font color='#B4530A'><b>관찰</b></font>", CELLC),
         "메모리 기판 강자이나 HBM 귀속 매출 문서 없음 (GDDR7≠HBM)"],
        ["SFA반도체", Paragraph("0회", CELLC),
         Paragraph("<font color='#B4530A'><b>관찰</b></font>", CELLC),
         "메모리 OSAT이나 HBM 적층 매출 근거 없음"]],
       [34 * mm, 30 * mm, 18 * mm, 96 * mm]))
A(Spacer(1, 3 * mm))
A(box([(BODY, "<b>'앞으로 HBM과 연관될 것 같다'는 전망은 편입 요건이 아니다.</b> "
              "심텍·SFA반도체는 관찰종목으로 남긴다 — HBM 매출이 공시에 잡히는 순간 "
              "정기변경에서 자동으로 재심사된다. 지수는 테마의 성장을 따라 커지되, "
              "기대를 앞질러 사지 않는다."),
       (BODY, "<b>같은 잣대를 해외에도 적용했다 (S6, 2026-07-29).</b> 글로벌 후보 8종 실사 결과: "
              "<b>Micron 편입</b>(앵커 — 메모리제조×HBM양산, 10-K 근거) · Camtek 관찰"
              "(HBM 2사 수주 $260M/2년 — 매출 전환·공시 시 재심) · TSMC·Onto·Advantest·"
              "Resonac·Besi 제외(HBM 귀속 매출 소명 불가). 앵커는 '사실 확인'이라 국경을 "
              "넘고, 비앵커는 '비율 소명'이라 공시 제도에 막힌다 — 규칙이 낸 결과다."),
       (SMALL, "판정 원칙: fail-closed (애매하면 제외). 오로스 편입은 규칙 C②의 문구"
               "('TSV·하이브리드본딩 등 HBM 고유공정')를 문서 그대로 적용한 결과. "
               "글로벌 판정 근거: docs/글로벌실사_판정근거_20260729.md")],
      title="이 지수의 정직성", title_bg=NAVY))
A(PageBreak())

# ═══════════════ 5. 운용 설계 ═══════════════
A(Paragraph("어떻게 굴리나", KICK))
A(Paragraph("추적오차의 적은 보수가 아니라 현금이다", H1))
A(Paragraph("지수 <b>12.5년</b> 실측 경로에 보수·매매비용·현금보유를 얹어 ETF NAV를 시뮬레이션했다. "
            "드래그 분해는 로그 항등식(합계=실측)이라 근사가 없다.", BODY))
A(Spacer(1, 2 * mm))
A(grid(["시나리오", "TER", "매매비용", "현금", "지수 대비 연간 부진"],
       [["기본", Paragraph("45bp", CELLC), Paragraph("30bp", CELLC),
         Paragraph("0%", CELLC), Paragraph("<b>53bp</b> (TER 45 + 비용 8)", CELL)],
        ["저보수", Paragraph("15bp", CELLC), Paragraph("10bp", CELLC),
         Paragraph("0%", CELLC), "18bp"],
        [Paragraph("<b>현금 1% 보유</b>", CELL), Paragraph("45bp", CELLC),
         Paragraph("30bp", CELLC), Paragraph("1%", CELLC),
         Paragraph("<b>78bp — 현금 몫이 24bp</b>", CELL)]],
       [30 * mm, 20 * mm, 22 * mm, 16 * mm, 90 * mm]))
A(Spacer(1, 2 * mm))
A(box([(BODY, "<b>현금 1%의 비용은 12.5년 기준 연 24bp</b>로 보수(45bp)의 절반 수준이다. "
              "직전 1년(+243% 강세장)만 보면 104bp로 보수의 2.3배였는데, 그 구간이 예외적으로 "
              "컸던 것이다 — 현금 드래그는 지수 상승률에 비례하기 때문이다."),
       (BODY, "게다가 <b>하락장에서는 부호가 뒤집혀 방어가 된다.</b> 실측 위기 4구간에서 "
              "현금 1%의 기여는 2018년 -72bp · 2020년 -335bp · 2022년 -59bp · "
              "2026년(진행중) -308bp였다. 따라서 현금 최소화는 강세장 전용 원칙이며, "
              "현물설정(in-kind) 극대화가 상시 원칙이다."),
       (BODY, "<b>환노출도 위기에서 완충으로 작동했다.</b> MU(USD 자산)를 환율 고정과 비교하면 "
              "위기 MDD 기여가 2018 +0.4 · 2020 +0.4 · 2022 +1.5%p — 원화가 위기 때 "
              "약세라 자연 헤지가 된다. 환헤지 없는 상품이 낙폭 관점에서 유리하다."),
       (SMALL, "시뮬 기간 2014-01-02~2026-07-29 (12.5년, 3,085거래일) · 분기 재고정 · "
               "연율화 편도회전율 28% · 편입 종목은 상장 시점에 따라 7→13종목 · "
               "MU는 FDR 시세 × USD/KRW 일별 환산")]))
A(Spacer(1, 5 * mm))
A(Paragraph("용량과 설정단위 — 숫자 두 개", BIG))
A(grid(["항목", "값", "결정 요인"],
       [["소화 가능 AUM", Paragraph("<b>1,741억 원</b>", CELLBC),
         "병목 넥스틴 — 참여율 20%·청산 5일 · <b>정규장 거래대금</b> 기준"],
        ["실측 거래대금 기준", Paragraph("2,296억 원", CELLC),
         "시간외·블록딜 포함 값. 원할 때 체결되지 않으므로 설계 기준으로 쓰지 않는다"],
        ["위기 구간 실측", Paragraph("<b><font color='#B3261E'>74~187억 원</font></b>", CELLBC),
         "2018 사이클붕괴 74억 · 2020 코로나 116억 · 2022 금리인상 187억 — "
         "낙폭보다 유동성이 먼저 마른다. <b>MU 편입도 이를 개선하지 못한다</b>"
         "(병목이 국내 꼬마주라서 — 앵커 유동성만 는다)"],
        ["7종목이던 시절", Paragraph("613억 원", CELLC),
         "당시 넥스틴 비중 10.6% — 12종목 재배분으로 용량 3.3배 개선"],
        ["설정단위(CU)", Paragraph("<b>30억 원 (30만 좌)</b>", CELLBC),
         "총괴리 8.4bp ≤ 허용 15bp · 0주 종목 없음 · MU 편입으로 20억→30억 상향"],
        ["정밀도 병목", Paragraph("SK하이닉스·MU", CELLC),
         "주당 140만·120만원 → 1CU에 각 265·325주 — 고가 정수주 격자 2개"]],
       [34 * mm, 34 * mm, 110 * mm]))
A(Spacer(1, 3 * mm))
A(box([(BODY, "<b>CU는 오늘 종가 한 점으로 정하지 않았다.</b> 반올림 격자는 주가에 민감해서 "
              "후보 순서가 뒤집힌다 — 오늘 마감가로는 20억도 통과하지만, 가격을 ±5% 흔들어 300회 "
              "다시 재면 <b>0.3%</b>가 허용치를 넘긴다(10억은 65%). "
              "300회 전부 허용치 안에 드는 최소 규모가 30억이다."),
       (SMALL, "허용치 15bp는 완화가 아니다 — 종전 지표는 현금 잔액을 빼고 세어 실제 이탈의 "
               "정확히 절반을 보고했다(그 척도의 '10bp'는 실제 20bp였다). 현금을 목표 0인 "
               "포지션으로 세어 넣어 바로잡았으므로 실질 기준은 20bp → 15bp로 엄격해졌다.")]))
A(PageBreak())

# ═══════════════ 6. 상장요건 + 정직 고지 ═══════════════
A(Paragraph("규정 점검", KICK))
A(Paragraph("상장요건 — 강화 방침 포함 전 요건 통과", H1))
A(grid(["항목", "기준", "실측", "판정"],
       [["구성종목 수 (상장규정)", Paragraph("≥ 10", CELLC),
         Paragraph("13", CELLC),
         Paragraph("<font color='#1E7B45'><b>PASS</b></font>", CELLC)],
        ["1종목 최대 비중", Paragraph("≤ 30%", CELLC),
         Paragraph("18.00% (한미반도체)", CELLC),
         Paragraph("<font color='#1E7B45'><b>PASS</b></font>", CELLC)],
        ["소수종목 테마형 20% (강화 방침)", Paragraph("≤ 20%", CELLC),
         Paragraph("18.00%", CELLC),
         Paragraph("<font color='#1E7B45'><b>PASS</b></font>", CELLC)]],
       [66 * mm, 26 * mm, 50 * mm, 36 * mm]))
A(Spacer(1, 2 * mm))
A(Paragraph("강화 방침(20%)은 12종목 시절 삼성전자 21.57%로 WARN이었다 — 규칙을 구부리지 않고 "
            "<b>자격자(MU) 편입만으로 해소됐다.</b> 앵커 40%를 3사 유동시총 비례로 나누자 "
            "최대비중이 14.54%(삼성)로 내려가고, 지수 최대는 한미반도체 18.00%가 됐다. "
            "규칙 기반 지수가 심사 리스크를 스스로 치유한 사례다.", BODY))
A(Spacer(1, 5 * mm))
A(box([(BODY, "<b>이 문서가 말하지 않은 것 — 한계와 가정.</b>"),
       (BODY, "· 용량의 거래대금은 최근 60일(강세장) 기준 — 거래가 식으면 용량도 준다. "
              "위기 구간 실측이 74~187억인 것이 그 증거다. 참여율 20%·청산 5일은 관측이 "
              "아니라 우리가 고른 가정이고, 용량은 여기에 정비례한다."),
       (BODY, "· 거래대금 정의가 소스마다 다르다. FnGuide 값은 시간외·블록딜을 포함해 "
              "대형주에서 정규장의 1.7~2.0배다. 설계 기준은 정규장으로 통일했다."),
       (BODY, "· 추적오차 시뮬의 리밸런싱은 분기 재고정 근사 — 실제 정기변경(심사)과 다를 수 있다."),
       (BODY, "· 위성 5종목의 노출도 값은 판정 스냅샷 기준 — 다음 사업보고서에서 갱신된다."),
       (BODY, "· <b>12.5년 수익률은 성과 주장에 쓰지 않는다.</b> 오늘 확정한 구성을 소급 재생한 "
              "값이라 사후선택이 세 겹(2026년 판정 통과 기업만 · 오늘의 비중 · 상장 즉시 편입) "
              "실려 있다. 크기도 쟀다 — 12종목 시절 같은 구성을 동일가중으로 돌리면 +1,117%로, "
              "차이 <b>+2,612%p가 오늘 비중을 소급한 프리미엄</b>이다(counterfactual.csv). "
              "반면 낙폭은 어느 비중이든 -45% 수준으로 같았다 — 이 문서가 수익률이 아니라 "
              "<b>낙폭(-44.9%)·위기 용량(74~187억)·드래그</b>를 앞세우는 이유다."),
       (BODY, "· MU 시세는 FDR × USD/KRW 일별 환산 — <b>미국 시세의 배당·분할 반영 방식이 "
              "국내 수정주가(PR) 계약과 동일한지는 검증되지 않았다</b>(MU 배당이 작아 왜곡은 "
              "제한적이나, 계약 명문화 전까지 한계로 고지)."),
       (BODY, "· 실제 ETF 상장은 자산운용사만 가능하다. 개인이 이 구성을 직접 복제하려면 "
              "정수 주 제약 때문에 최소 <b>약 3억 3천만원</b>(비중편차 100bp 허용) 규모가 "
              "필요하다. 이 값은 정수 주 격자라 가격 스냅샷에 민감하다 — 자릿수로만 읽을 것. "
              "MU는 해외주식이라 환전·해외 수수료·양도세(22%)가 별도로 붙는다."),
       (SMALL, "본 문서는 학습 목적의 모의 설계서다. 투자 권유가 아니며, 어떤 매매의 근거도 되지 않는다. "
               "모든 수치는 jeongga_hbm_etf 저장소의 코드로 재현 가능하다 (오프라인 테스트 19종 343건).")],
      title="정직 고지", title_bg=NAVY))

doc.build(E)
print(f"저장: {OUT}")
