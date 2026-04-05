"""
Claude API 서비스
- 에이전트 투자 판단 + 리포트 생성
- 시장 국면 감지
- 시장 내러티브 생성
- 사후 검증
- 라운드테이블 / 토론
- API 비용 트래킹
"""

import json
from datetime import datetime
from groq import AsyncGroq

from backend.config import GROQ_API_KEY, CLAUDE_MAX_TOKENS
from backend.database import execute as db_execute

# ── 임시: Groq으로 운영 (Claude API 크레딧 충전 후 아래 주석 교체) ──
# 교체 방법:
#   1. from anthropic import AsyncAnthropic
#   2. from backend.config import ANTHROPIC_API_KEY, CLAUDE_MODEL
#   3. client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
#   4. _call_claude 내부를 원래 Claude 호출 코드로 복원
GROQ_MODEL = "llama-3.3-70b-versatile"
_client: AsyncGroq | None = None


def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=GROQ_API_KEY)
    return _client


async def _call_claude(prompt: str, system: str, purpose: str) -> str:
    """Groq 호출 (Claude API 크레딧 충전 후 Claude로 교체 예정)"""
    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=min(CLAUDE_MAX_TOKENS, 8000),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        text = response.choices[0].message.content or ""
        # 비용 트래킹 (Groq는 무료이므로 0으로 기록)
        await db_execute(
            """INSERT INTO api_usage (model, input_tokens, output_tokens, estimated_cost, purpose)
               VALUES ($1, $2, $3, $4, $5)""",
            (GROQ_MODEL, 0, 0, 0.0, purpose),
        )
        return text
    except Exception as e:
        print(f"[Groq/_call_claude] 오류: {e}")
        return ""


# ── Plan A: 에이전트별 고정 매크로 프레임워크 ──────────────────────────

_MACRO_LENS_AGENTS = {"macro", "strategist", "bear"}

_MACRO_FRAMEWORK = {
    "macro": """
## 핵심 분석 프레임워크 (항상 적용)
모든 자산 가치 = Cash / (R - G) 공식을 기준으로 판단하라.

- **R(할인율)이 최우선 변수**: 인플레이션 고착화·지정학 리스크·Fed Put 소멸 여부를
  가장 먼저 점검한다. 케빈 워시(반QE·프로QT) 류 매파 인사 부상 시 R의 구조적 상승을 경고한다.
- **베어 플래트닝 = 최고 위험 신호**: 단기금리 > 장기금리 수렴은 긴축 장기화 신호.
  FICC 기계적 매도로 전 자산 동반 하락 위험이 있다.
- **미국 10년물 4.5% 임계값**: 이를 돌파하면 자산 배분 모델의 위험 자산 이탈이 가속된다.
- **금(Gold)+주식 동반 하락 = 유동성 경색**: 안전 자산이 아닌 'Cash is King' 신호.
  이 국면에서는 역발상 매수가 아니라 현금 보존을 우선한다.
- **헤지 자산군**: 호르무즈·공급망 위기 시 에너지·자원주(XOM, CVX, LNG 등)를
  인플레이션 방어 수단으로 적극 검토한다.
- **현금은 공격적 자산**: 레버리지 풀 베팅보다 일정 현금 유지가
  변동성 국면에서 심리적 우위와 저가 매수 기회를 보장한다.
""",

    "strategist": """
## 핵심 분석 프레임워크 (항상 적용)
가치 = Cash / (R - G). 장기 관점에서 R과 G 모두를 철저히 점검하라.

- **밸류에이션 리레이팅 위험**: R이 오르면 분모가 커져 멀티플이 축소된다.
  성장이 정체되는 순간 시장은 성장주를 가치주(PBR, 배당) 기준으로 재평가한다.
- **이익 반응 테스트 (핵심 매도 시그널)**: 실적이 예상치를 상회해도 주가가
  무반응이거나 하락한다면 시장이 이미 이익 피크아웃을 확인한 것이다. 즉시 비중 축소를 검토한다.
- **ROIC 우선 원칙**: 고금리 환경에서 자본 비용(R)을 초과하는 ROIC를 가진 기업만이
  진정한 가치를 창출한다. ROIC < WACC 기업은 원천 배제한다.
- **헤지 자산군**: 인플레이션 국면에서 에너지·자원주(XOM, CVX, LNG, BHP 등)를
  장기 포트폴리오 방어 수단으로 적극 검토한다.
- **현금 보존 우선**: 불확실성 구간에서는 수익률보다 생존이 먼저다.
  확신이 없으면 현금을 유지하고, 데이터 확인 후 진입한다.
""",

    "bear": """
## 핵심 분석 프레임워크 (항상 적용)
하락 베팅의 근거는 항상 R(할인율)의 역습에서 출발한다.

- **베어 플래트닝 = 진입 조건 강화**: 단기금리가 장기금리보다 빠르게 오를수록
  인버스 ETF 비중 확대의 정당성이 높아진다.
- **미국 10년물 4.5% 돌파**: 자산 배분 모델의 기계적 이탈이 시작되는 임계값.
  이 수준에서 인버스 포지션 강화를 적극 검토한다.
- **1973년 스태그플레이션 시나리오**: 호르무즈 해협 긴장 장기화 시 공급망 인플레이션 고착.
  금리 인하 카드 봉쇄 → 구조적 약세장의 전형적 패턴이다.
- **금+주식 동반 하락 = 최고 위험**: 유동성 경색 신호. 이 국면이 감지되면
  인버스 포지션 외 모든 자산을 현금화하는 것을 우선 검토한다.
""",
}


def _get_agent_macro_lens(agent_id: str) -> str:
    """Plan A: macro/strategist/bear 에이전트 고정 프레임워크 반환"""
    return _MACRO_FRAMEWORK.get(agent_id, "")


# ── Plan B: 동적 시장 경고 컨텍스트 ────────────────────────────────────

def _build_market_warning_context(market_context: dict) -> str:
    """
    market_context에서 임계값 초과 시그널을 감지 → 경고 블록 생성
    모든 에이전트 프롬프트에 동적으로 주입
    """
    warnings = []

    macro = market_context.get("fred", {}) or {}

    # 미국 10년물 금리 임계값 (4.5%)
    us10y = macro.get("10Y_YIELD") or macro.get("DGS10")
    if us10y and float(us10y) >= 4.5:
        warnings.append(
            f"🚨 **미국 10년물 금리 {us10y:.2f}%** — 4.5% 임계값 돌파. "
            "자산 배분 모델의 위험 자산 이탈 가속 구간. 추격 매수 자제."
        )

    # 베어 플래트닝 (10Y - 2Y 스프레드)
    us2y = macro.get("2Y_YIELD") or macro.get("DGS2")
    if us10y and us2y:
        spread = float(us10y) - float(us2y)
        if spread < 0.3:
            warnings.append(
                f"⚠️ **베어 플래트닝 감지** — 10년물({us10y:.2f}%) - 2년물({us2y:.2f}%) "
                f"스프레드 {spread:.2f}%p. 긴축 장기화 신호, 할인율(R) 구조적 상승 중."
            )

    # 금+주식 동반 하락 (유동성 경색)
    gold_drop = market_context.get("gold_drop", False)
    equity_drop = market_context.get("equity_drop", False)
    if gold_drop and equity_drop:
        warnings.append(
            "🚨 **금+주식 동반 하락 감지** — 'Cash is King' 유동성 경색 신호. "
            "안전 자산 선호가 아닌 전 자산 현금화 국면. 신규 매수 전면 자제."
        )

    if not warnings:
        return ""

    return "\n## ⚡ 시장 경고 시그널 (즉시 반영)\n" + "\n".join(f"- {w}" for w in warnings) + "\n"


# ── 시장 국면 감지 ─────────────────────────────────────────────────

async def detect_market_regime(macro_data: dict, sector_data: dict, market: str) -> dict:
    """
    KR 또는 US 시장 국면 분류
    반환: {"regime": "상승장|하락장|횡보|변동성급등|유동성경색", "confidence": 0~1}
    """
    system = "당신은 시장 국면을 분석하는 전문가입니다. JSON으로만 응답하세요."

    fred = macro_data.get("fred", {}) or {}
    us10y = fred.get("10Y_YIELD") or fred.get("DGS10")
    us2y  = fred.get("2Y_YIELD")  or fred.get("DGS2")
    spread_note = ""
    if us10y and us2y:
        spread = float(us10y) - float(us2y)
        spread_note = f"\n금리 스프레드 (10년 - 2년): {spread:.2f}%p ({'베어 플래트닝' if spread < 0.3 else '정상'})"

    prompt = f"""
다음 데이터를 보고 {market} 시장의 현재 국면을 분류하세요.

거시 데이터:
{json.dumps(macro_data, ensure_ascii=False, indent=2)}{spread_note}

섹터 데이터:
{json.dumps(sector_data, ensure_ascii=False, indent=2)}

국면 분류 기준:
- 상승장: 이익 성장과 멀티플 동반 확대, R 안정적
- 하락장: 이익 또는 멀티플 수축, R 상승 압력
- 횡보: 상방·하방 모두 제한, 박스권 범피 장세
- 변동성급등: VIX 급등, 방향성 없는 급등락
- 유동성경색: 금+주식 동반 하락, 전 자산 현금화, Cash is King 국면

다음 JSON 형식으로만 응답:
{{"regime": "위 5개 중 하나", "confidence": 0.0~1.0, "reason": "한 줄 이유"}}
"""
    result = await _call_claude(prompt, system, f"regime_detection_{market}")
    try:
        return json.loads(result.strip())
    except Exception:
        return {"regime": "횡보", "confidence": 0.5, "reason": "분석 실패"}


# ── 시장 내러티브 생성 ─────────────────────────────────────────────

async def generate_market_narrative(macro_data: dict, sector_data: dict, regime: str, market: str) -> str:
    """
    "지금 왜 이런 시장인가" 한 단락 서술
    초보자도 이해할 수 있는 언어
    """
    system = "당신은 주식 초보자도 이해할 수 있게 시장을 설명하는 전문가입니다."

    # 금리 스프레드 계산
    fred = macro_data.get("fred", {}) or {}
    us10y = fred.get("10Y_YIELD") or fred.get("DGS10")
    us2y  = fred.get("2Y_YIELD")  or fred.get("DGS2")
    rate_context = ""
    if us10y and us2y:
        spread = float(us10y) - float(us2y)
        if spread < 0.3:
            rate_context = f"\n참고: 현재 베어 플래트닝 진행 중 (스프레드 {spread:.2f}%p). 이를 쉬운 말로 포함할 것."
        if float(us10y) >= 4.5:
            rate_context += f"\n참고: 미국 10년물 금리 {us10y:.2f}%로 4.5% 임계값 돌파. 자산 가치 압박 중."

    prompt = f"""
현재 {market} 시장 국면: {regime}

거시 데이터:
{json.dumps(macro_data, ensure_ascii=False, indent=2)}

섹터 흐름:
{json.dumps(sector_data, ensure_ascii=False, indent=2)}{rate_context}

"지금 왜 이런 시장인가"를 주식을 잘 모르는 사람도 이해할 수 있게 2~3문장으로 서술하세요.
전문 용어 사용 시 괄호로 설명을 추가하세요. 한국어로 작성.
"""
    return await _call_claude(prompt, system, f"market_narrative_{market}")


# ── 에이전트 투자 판단 ─────────────────────────────────────────────

async def generate_agent_decision(
    agent_config,
    market_context: dict,
    candidate_stocks: list[dict],
    current_positions: list[dict],
    recent_logs: list[dict],
    recent_losses: list[dict] | None = None,
    extra_context: dict | None = None,
    consensus_map: dict | None = None,
) -> dict:
    """
    에이전트 투자 판단 생성
    반환: {
        "decision": "buy|hold|pass",
        "ticker": str | None,
        "market": "KR|US",
        "price": float,
        "entry_advice": str,
        "thesis": str,
        "next_condition": str,  (다음 판단 조건)
        "risk_note": str,       (리스크 한 줄)
        "confidence": str,      (low|medium|high)
        "report_md": str
    }
    """
    # Plan A: macro/strategist/bear — 고정 프레임워크 시스템 프롬프트에 삽입
    macro_lens = _get_agent_macro_lens(agent_config.agent_id)

    # 에이전트별 핵심 데이터 레이블
    _KEY_DATA_LABELS = {
        "technical_score": "기술적 스코어(RSI·이동평균·거래량 종합)",
        "fundamental_score": "재무 스코어(PBR·PER·ROIC 종합)",
        "pbr": "PBR(주가순자산비율) — 저평가 여부",
        "per": "PER(주가수익비율) — 수익성 대비 주가",
        "roic": "ROIC(투하자본수익률) — 자본 효율성",
        "revenue_growth": "매출 성장률 — 성장 모멘텀",
        "foreign_net_3d": "외국인 3일 순매수 수급",
        "institution_net_3d": "기관 3일 순매수 수급",
        "pct_from_high": "52주 고점 대비 하락률",
        "recent_news": "최근 종목 뉴스",
        "sector_etf": "섹터 ETF 수익률 흐름",
        "fred": "FRED 금리 데이터(금리 방향)",
        "narrative": "오늘의 시장 내러티브",
        "fear_greed": "공포탐욕지수(심리 극단 여부)",
        "vix": "VIX(시장 변동성지수)",
        "regime": "시장 국면(상승/하락/횡보/변동성)",
        "exchange_rate": "원달러 환율(달러 자산 매수 비용)",
        "gross_margin": "매출총이익률 — 비즈니스 경쟁력",
        "fcf": "FCF(잉여현금흐름) — 실제 현금 창출력",
        "debt_ratio": "부채비율 — 재무 건전성",
        "gap_pct": "갭(gap) % — 전일 종가 대비 당일 시가 괴리율 (양수=갭상승, 음수=갭하락)",
        "hy_spread": "HY 크레딧 스프레드 — 하이일드 채권 위험 프리미엄 (높을수록 신용 위험 증가)",
        "ig_spread": "IG 크레딧 스프레드 — 투자등급 채권 위험 프리미엄",
    }
    key_data_lines = "\n".join(
        f"  - {_KEY_DATA_LABELS.get(k, k)}"
        for k in (agent_config.key_data or [])
    )
    key_data_section = f"\n핵심 판단 데이터 (당신의 전략상 가장 중요한 항목):\n{key_data_lines}" if key_data_lines else ""

    # 금지 규칙 섹션 (에이전트 독립성 강화)
    forbidden_topics = getattr(agent_config, "forbidden_topics", [])
    forbidden_section = ""
    if forbidden_topics:
        forbidden_lines = "\n".join(f"  - {t}" for t in forbidden_topics)
        forbidden_section = f"\n❌ 절대 언급·사용 금지 항목 (이 에이전트 전략과 무관):\n{forbidden_lines}\n"

    system = f"""당신은 '{agent_config.name_kr}'라는 AI 투자 에이전트입니다.
페르소나: {agent_config.persona}
전략: {agent_config.strategy}
투자 시간축: {agent_config.time_horizon}
리포트 스타일: {agent_config.report_style}
{macro_lens}{key_data_section}{forbidden_section}

모든 판단은 한국어로 작성하세요.
전문 용어 사용 시 반드시 괄호로 설명을 추가하세요. (예: PBR(주가순자산비율))
숫자 근거는 반드시 의미 해석을 포함하세요.

⚠️ 데이터 누락 처리 원칙:
- "⚠️없음"으로 표시된 항목은 데이터가 수집되지 않은 것이다. 해당 항목을 투자 근거로 사용하지 말 것.
- data_gaps 필드가 있는 종목은 누락 데이터를 리포트에 명시할 것.
- 당신의 required_data(핵심 판단 데이터)가 "⚠️없음"인 종목은 pass 처리할 것.

📋 판단 구조 규칙:
- hold(관망): 관심 종목이 있으나 아직 진입 조건 미충족 — 추후 재검토 예정
- pass: 오늘 이 전략 기준으로 적합한 종목 자체가 없음 — 당분간 재검토 불필요"""

    # Plan B: 모든 에이전트 — 임계값 초과 시 동적 경고 주입
    warning_context = _build_market_warning_context(market_context)

    # 내러티브 섹션 (Task 5: 거시 뉴스 시그널 강조)
    narrative_section = ""
    narrative_kr = market_context.get("narrative_kr", "")
    narrative_us = market_context.get("narrative_us", "")
    if narrative_kr or narrative_us:
        narrative_section = "\n## 오늘의 시장 내러티브 (거시 뉴스 요약)\n"
        if narrative_kr:
            narrative_section += f"**[국내]** {narrative_kr}\n"
        if narrative_us:
            narrative_section += f"**[미국]** {narrative_us}\n"

    # 최근 손절 내역 섹션 (Task 3)
    loss_section = ""
    if recent_losses:
        loss_lines = "\n".join(
            f"- {l.get('ticker')} {l.get('pnl_pct', 0):+.1f}% ({l.get('created_at', '')[:10]})"
            for l in recent_losses
        )
        loss_section = f"\n## 최근 30일 손절 내역 (경계 참고)\n{loss_lines}\n(위 종목 재진입 시 신중하게 판단할 것)\n"

    # extra_context 섹션 구성
    extra = extra_context or {}
    extra_section = ""

    exchange_rate = extra.get("exchange_rate")
    if exchange_rate:
        extra_section += f"\n**현재 환율**: {exchange_rate:,.0f} 원/달러 (미국 주식 매수 시 참고)\n"

    mdd_info = extra.get("mdd")
    if mdd_info and (mdd_info.get("mdd", 0) < -3 or mdd_info.get("current_drawdown", 0) < -2):
        extra_section += (
            f"**포트폴리오 MDD**: 최대 낙폭 {mdd_info['mdd']:+.1f}% | "
            f"현재 고점 대비 {mdd_info['current_drawdown']:+.1f}% | 고점 수익률 {mdd_info['peak']:+.1f}%\n"
        )
        if mdd_info.get("current_drawdown", 0) < -5:
            extra_section += "⚠️ 현재 고점 대비 -5% 이상 낙폭 — 신규 매수 전 리스크 재검토 권고\n"

    sector_conc = extra.get("sector_concentration")
    if sector_conc:
        conc_lines = " | ".join(f"{k} {v}%" for k, v in sector_conc.items())
        extra_section += f"**현재 섹터 집중도**: {conc_lines}\n"
        if any(v >= 60 for v in sector_conc.values()):
            extra_section += "⚠️ 특정 섹터 60%+ 집중 — 동일 섹터 추가 매수 자제 권고\n"

    sector_etf = extra.get("sector_etf")
    if sector_etf:
        kr_etf = [e for e in sector_etf if e.get("market") == "KR"]
        us_etf = [e for e in sector_etf if e.get("market") == "US"]
        def _etf_line(e):
            r1 = e.get('return_1d')
            r5 = e.get('return_5d')
            r1s = f"{r1:+.1f}%" if r1 is not None else "⚠️없음"
            r5s = f"{r5:+.1f}%" if r5 is not None else "⚠️없음"
            return f"  {e.get('etf_name', e.get('etf_ticker'))}: 1일 {r1s} / 5일 {r5s}"
        if kr_etf:
            extra_section += "\n**국내 섹터 ETF 흐름**\n" + "\n".join(_etf_line(e) for e in kr_etf) + "\n"
        if us_etf:
            extra_section += "\n**미국 섹터 ETF 흐름**\n" + "\n".join(_etf_line(e) for e in us_etf) + "\n"

    # 보유 포지션에 PnL 요약 추가
    pos_summary = []
    for p in current_positions:
        pnl = p.get("pnl_pct")
        pnl_str = f"{pnl:+.1f}%" if pnl is not None else "⚠️없음"
        thesis = p.get("thesis", "테제 없음")
        pos_summary.append({
            "ticker": p.get("ticker"), "name": p.get("name"),
            "status": p.get("status"), "pnl_pct": pnl_str,
            "thesis": thesis,
        })

    prompt = f"""
## 현재 시장 상황 (거시 수치)
국면: KR={market_context.get('regime_kr')} / US={market_context.get('regime_us')}
VIX: {market_context.get('vix')} | 공포탐욕지수: {market_context.get('fear_greed')}
FRED 금리: {json.dumps(market_context.get('fred', {}), ensure_ascii=False)}
gold 변화: {market_context.get('gold_change_pct', 0):+.1f}% | S&P500 변화: {market_context.get('spx_change_pct', 0):+.1f}%
{extra_section}{narrative_section}{warning_context}{loss_section}
## 보유 포지션 ({len(current_positions)}개) — 현재 수익률 포함
{json.dumps(pos_summary, ensure_ascii=False, indent=2)}

## 후보 종목 (스코어 상위 + 거래량 급등 포함)
{json.dumps(candidate_stocks[:20], ensure_ascii=False, indent=2)}

## 최근 30일 내 판단 기록
{json.dumps(recent_logs[-10:], ensure_ascii=False, indent=2)}

## 다른 에이전트 보유 현황 (중복 진입 참고용 — 판단은 독립적으로)
{json.dumps(consensus_map or {}, ensure_ascii=False, indent=2)}

---

위 정보를 바탕으로 오늘의 투자 판단을 하세요.

**판단 기준:**
- buy: 지금 매수할 종목이 있다
- hold: 관심 종목이 있으나 진입 조건 미충족 (다음 조건 명시 필수)
- pass: 오늘 내 전략 기준으로 적합한 종목 없음

**반드시 다음 JSON 형식으로 응답:**
{{
  "decision": "buy 또는 hold 또는 pass",
  "ticker": "종목코드 (buy일 때만, 나머지 null)",
  "market": "KR 또는 US (buy일 때만)",
  "name": "종목명 (buy일 때만)",
  "price": 매수가격_숫자 (buy일 때만, 나머지 0),
  "entry_advice": "기준가 X원. 하락 시 Y원에서 추가 매수 / 일괄매수 (buy일 때만, 나머지 null)",
  "thesis": "투자 테제 한 문장 (buy/hold일 때)",
  "next_condition": "다음에 언제 다시 판단할지 — 예: 'RSI 50 이하로 내려오면 재검토' / '다음 주 실적 발표 후 확인'",
  "risk_note": "이 판단이 틀릴 수 있는 이유 한 줄",
  "confidence": "low 또는 medium 또는 high",
  "report_md": "## [{agent_config.name_kr}] 오늘의 판단\\n\\n**[결론]** buy/hold/pass\\n\\n**[이유]** 이 전략 기준 2~3개 근거만\\n\\n**[행동]** 지금 할 행동 구체적으로\\n\\n**[다음 조건]** 언제 다시 볼지\\n\\n**[리스크]** 틀릴 수 있는 이유",
  "pass_reason": "pass/hold 선택 시 이유 (buy면 null)"
}}
"""
    result = await _call_claude(prompt, system, f"agent_decision_{agent_config.agent_id}")
    try:
        if "```json" in result:
            result = result.split("```json")[1].split("```")[0].strip()
        elif "```" in result:
            result = result.split("```")[1].split("```")[0].strip()
        return json.loads(result)
    except Exception:
        return {
            "decision": "pass",
            "ticker": None,
            "market": "KR",
            "name": None,
            "price": 0,
            "entry_advice": None,
            "thesis": None,
            "next_condition": None,
            "risk_note": None,
            "confidence": "low",
            "report_md": f"## 판단 오류\n\n분석 중 오류가 발생했습니다.\n\n원본:\n{result}",
            "pass_reason": "분석 오류",
        }


# ── 포지션 모니터링 ─────────────────────────────────────────────────

async def monitor_position(
    agent_config,
    position: dict,
    current_price: float,
    market_context: dict,
    original_thesis: str,
    holding_days: int = 0,
) -> dict:
    """
    보유 포지션 테제 유효성 체크
    반환: {"status": "hold|watch|sell", "report_md": str, "thesis_valid": bool}
    """
    # Plan A: strategist — 이익 반응 테스트 시스템 프롬프트에 삽입
    earnings_test_note = ""
    if agent_config.agent_id == "strategist":
        earnings_test_note = """
이익 반응 테스트 원칙:
- 실적이 예상치를 상회했음에도 주가가 무반응이거나 하락했다면,
  시장이 이미 이익 피크아웃을 확인한 것이다. 즉시 'watch' 또는 'sell'로 전환하라.
- 이익 성장이 지속되는 동안만 멀티플(PER, PBR)이 유지된다.
  성장 둔화 조짐이 보이면 가치주 기준(PBR, 배당)으로 재평가하라."""

    system = f"""당신은 '{agent_config.name_kr}' AI 에이전트입니다.
페르소나: {agent_config.persona}
경계 트리거: {agent_config.watch_trigger}
리포트 스타일: {agent_config.report_style}{earnings_test_note}"""

    # Plan B: 동적 경고 주입
    warning_context = _build_market_warning_context(market_context)

    pnl_pct = (current_price - position["price"]) / position["price"] * 100

    # 급락 감지 정보 (price_spikes가 market_context에 있을 경우)
    spike_note = ""
    spike_pct = market_context.get("price_spikes", {}).get(position.get("ticker", ""), None)
    if spike_pct is not None:
        spike_note = f"\n⚠️ **오늘 급락 감지: {spike_pct:+.1f}%** — 즉각적 테제 재검토 필요"

    # 최신 뉴스 섹션
    news_list = position.get("recent_news", [])
    news_section = ""
    if news_list:
        news_section = "\n## 최신 종목 뉴스\n" + "\n".join(f"- {n}" for n in news_list) + "\n"
    else:
        news_section = "\n## 최신 종목 뉴스\n- ⚠️없음 (뉴스 수집 실패 또는 없음)\n"

    prompt = f"""
## 보유 포지션
종목: {position.get('name', position['ticker'])} ({position['ticker']})
매수가: {position['price']:,.0f}
현재가: {current_price:,.0f}
수익률: {pnl_pct:+.2f}%
보유 기간: {holding_days}일
매수 테제: {original_thesis}
현재 상태: {position.get('status', 'hold')}{spike_note}
{news_section}
## 현재 시장 상황
국면: KR={market_context.get('regime_kr')} / US={market_context.get('regime_us')}
VIX: {market_context.get('vix')} | 공포탐욕지수: {market_context.get('fear_greed')}
{warning_context}
---

이 포지션의 투자 테제가 아직 유효한지 판단하세요.

**반드시 다음 JSON 형식으로 응답:**
{{
  "status": "hold 또는 watch 또는 sell",
  "thesis_valid": true 또는 false,
  "report_md": "## 포지션 점검\\n\\n### 핵심 판단\\n...\\n\\n### 데이터 근거\\n...\\n\\n### AI 해석\\n...",
  "sell_reason": "sell 선택 시 이유 (hold/watch면 null)"
}}
"""
    result = await _call_claude(prompt, system, f"position_monitor_{agent_config.agent_id}")
    try:
        if "```json" in result:
            result = result.split("```json")[1].split("```")[0].strip()
        elif "```" in result:
            result = result.split("```")[1].split("```")[0].strip()
        return json.loads(result)
    except Exception:
        return {
            "status": "hold",
            "thesis_valid": True,
            "report_md": f"## 모니터링 오류\n\n{result}",
            "sell_reason": None,
        }


# ── 사후 검증 ──────────────────────────────────────────────────────

async def generate_postmortem(
    agent_config,
    ticker: str,
    name: str,
    buy_report: str,
    sell_report: str,
    pnl_pct: float,
    pnl_pct_krw: float,
    holding_days: int,
) -> str:
    """사후 검증 리포트 생성"""
    system = f"""당신은 '{agent_config.name_kr}' AI 에이전트입니다.
자신의 투자 결정을 솔직하게 회고하세요. 맞았으면 왜 맞았는지, 틀렸으면 왜 틀렸는지."""

    prompt = f"""
## 종료된 포지션
종목: {name} ({ticker})
수익률: {pnl_pct:+.2f}% (환율 반영 원화 실질: {pnl_pct_krw:+.2f}%)
보유 기간: {holding_days}일

## 매수 당시 리포트
{buy_report}

## 매도 당시 리포트
{sell_report}

---

이 투자에 대해 솔직하게 사후 검증하세요:
1. 왜 맞았나 / 왜 틀렸나
2. 어떤 신호를 놓쳤나 (할인율 변화, 이익 반응 테스트, 베어 플래트닝 등)
3. 같은 상황이 다시 오면 어떻게 할 것인가

마크다운 형식으로 작성. 한국어.
"""
    return await _call_claude(prompt, system, f"postmortem_{agent_config.agent_id}")


# ── 주간 라운드테이블 ──────────────────────────────────────────────

async def generate_roundtable(agents_summaries: list[dict]) -> str:
    """7개 에이전트 주간 요약 → 라운드테이블 토론 리포트"""
    system = "당신은 7명의 AI 투자자가 참여하는 주간 투자 토론의 진행자입니다."
    prompt = f"""
다음은 이번 주 7개 AI 에이전트의 투자 요약입니다:

{json.dumps(agents_summaries, ensure_ascii=False, indent=2)}

이를 바탕으로 주간 라운드테이블 토론 리포트를 작성하세요:
1. 각 에이전트의 이번 주 핵심 판단 요약
2. 에이전트 간 의견 충돌·합의 분석 (특히 R 상승 대응 방식의 차이)
3. 다음 주 시장 전망 (7개 시각 통합, R-G 균형 관점 포함)

마크다운 형식. 한국어. 초보자도 읽기 쉽게.
"""
    return await _call_claude(prompt, system, "roundtable_weekly")


# ── 에이전트 간 토론 ────────────────────────────────────────────────

async def generate_debate(
    ticker: str,
    name: str,
    bull_agent: str,
    bull_report: str,
    bear_agent: str,
    bear_report: str,
) -> str:
    """같은 종목 반대 포지션 → 토론 리포트"""
    system = "당신은 두 AI 투자자의 상반된 의견을 분석하는 중립적 분석가입니다."
    prompt = f"""
종목: {name} ({ticker})

## {bull_agent} (매수 측)
{bull_report}

## {bear_agent} (매도/회의 측)
{bear_report}

---

두 의견을 분석하고 토론 리포트를 작성하세요:
1. 핵심 논거 비교 (성장(G) vs 할인율(R) 관점 포함)
2. 각각의 설득력 평가
3. 어떤 조건이 충족되면 누가 맞을지 (금리 방향, 이익 반응 등)

마크다운 형식. 한국어. 초보자도 이해하기 쉽게.
"""
    return await _call_claude(prompt, system, f"debate_{ticker}")


# ── 오늘의 한 줄 요약 ──────────────────────────────────────────────

async def generate_daily_summary(agents_decisions: list[dict]) -> str:
    """7개 에이전트 오늘 판단 → 한 줄 요약"""
    system = "한 문장으로 오늘 AI 투자자들의 전체 분위기를 요약하세요."
    prompt = f"""
오늘 7개 AI 에이전트의 투자 결정:
{json.dumps(agents_decisions, ensure_ascii=False, indent=2)}

위 내용을 한 문장(40자 이내)으로 요약하세요. 한국어.
예: "금리 불확실성 속 반도체 분할매수 우세, 베어·컨트라리안은 현금 대기."
"""
    return await _call_claude(prompt, system, "daily_summary")
