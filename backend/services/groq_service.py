"""
Groq API 서비스 — 빠른 조사·서칭 담당
- 뉴스 헤드라인 요약 및 매크로 시그널 추출
- 종토방 게시글 제목 NLP 감성 분석
- 후보 종목 초기 필터링 (Claude 호출 전 사전 선별)

역할 분담:
  Groq  → 수집된 raw 데이터의 빠른 해석·분류·요약 (저렴, 고속)
  Claude → 최종 투자 판단·3단 리포트·사후 검증 (정밀, 고비용)
"""

import json
from groq import AsyncGroq
from backend.config import GROQ_API_KEY

# llama-3.3-70b-versatile: 빠르고 저렴, 한국어 지원 양호
GROQ_MODEL = "llama-3.3-70b-versatile"

_client: AsyncGroq | None = None


def get_groq_client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=GROQ_API_KEY)
    return _client


async def _call_groq(prompt: str, system: str, max_tokens: int = 1024) -> str:
    """Groq 호출 (비용 트래킹 없음 — 충분히 저렴)"""
    if not GROQ_API_KEY:
        return ""
    try:
        client = get_groq_client()
        response = await client.chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        print(f"[Groq] 오류: {e}")
        return ""


# ── 뉴스 매크로 시그널 추출 ────────────────────────────────────────

async def summarize_macro_news(news_items: list[dict]) -> dict:
    """
    RSS 뉴스 헤드라인 → 핵심 매크로 시그널 추출
    반환: {
        "summary": str,          # 2~3줄 요약
        "key_signals": list[str], # 핵심 시그널 목록
        "risk_level": "낮음|보통|높음",
        "rate_signal": "인상압력|동결|인하압력|불명확"
    }
    """
    if not news_items:
        return {"summary": "", "key_signals": [], "risk_level": "보통", "rate_signal": "불명확"}

    headlines = "\n".join(
        f"- [{n['source']}] {n['title']}" for n in news_items[:30]
    )

    system = "당신은 금융 뉴스에서 투자에 중요한 매크로 시그널을 추출하는 분석가입니다. JSON으로만 응답하세요."
    prompt = f"""
다음 뉴스 헤드라인에서 투자자에게 중요한 매크로 시그널을 추출하세요.

{headlines}

다음 JSON 형식으로 응답:
{{
  "summary": "오늘 뉴스 핵심 2~3줄 요약 (한국어)",
  "key_signals": ["시그널1", "시그널2", ...],
  "risk_level": "낮음 또는 보통 또는 높음",
  "rate_signal": "인상압력 또는 동결 또는 인하압력 또는 불명확"
}}
"""
    result = await _call_groq(prompt, system, max_tokens=512)
    try:
        if "```json" in result:
            result = result.split("```json")[1].split("```")[0].strip()
        elif "```" in result:
            result = result.split("```")[1].split("```")[0].strip()
        return json.loads(result)
    except Exception:
        return {"summary": result[:200], "key_signals": [], "risk_level": "보통", "rate_signal": "불명확"}


# ── 종목 뉴스 이벤트 분류 ──────────────────────────────────────────

async def classify_stock_news(ticker: str, name: str, news_items: list[dict]) -> dict:
    """
    개별 종목 뉴스 → 투자 이벤트 분류
    반환: {
        "sentiment": "긍정|부정|중립",
        "event_type": "실적|공시|규제|수주|기타",
        "summary": str,
        "action_signal": "매수검토|매도검토|관망"
    }
    """
    if not news_items:
        return {"sentiment": "중립", "event_type": "기타", "summary": "", "action_signal": "관망"}

    headlines = "\n".join(f"- {n['title']}" for n in news_items[:10])

    system = "당신은 개별 종목 뉴스를 분류하는 금융 분석가입니다. JSON으로만 응답하세요."
    prompt = f"""
종목: {name} ({ticker})

뉴스 헤드라인:
{headlines}

다음 JSON으로 응답:
{{
  "sentiment": "긍정 또는 부정 또는 중립",
  "event_type": "실적 또는 공시 또는 규제 또는 수주 또는 기타",
  "summary": "핵심 이벤트 한 줄 요약",
  "action_signal": "매수검토 또는 매도검토 또는 관망"
}}
"""
    result = await _call_groq(prompt, system, max_tokens=256)
    try:
        if "```json" in result:
            result = result.split("```json")[1].split("```")[0].strip()
        elif "```" in result:
            result = result.split("```")[1].split("```")[0].strip()
        return json.loads(result)
    except Exception:
        return {"sentiment": "중립", "event_type": "기타", "summary": "", "action_signal": "관망"}


# ── 종토방 NLP 감성 분석 ──────────────────────────────────────────

async def analyze_board_sentiment(ticker: str, posts: list[dict]) -> dict:
    """
    종토방 게시글 제목 NLP 분석 (agree/disagree 카운트 대체)
    반환: {
        "sentiment_score": float,  # -1.0 ~ +1.0
        "dominant_emotion": "공포|탐욕|기대|실망|혼조",
        "summary": str
    }
    """
    if not posts:
        return {"sentiment_score": 0.0, "dominant_emotion": "혼조", "summary": ""}

    titles = "\n".join(f"- {p['title']}" for p in posts[:30])

    system = "당신은 주식 커뮤니티 게시글 감성을 분석하는 전문가입니다. JSON으로만 응답하세요."
    prompt = f"""
종목코드: {ticker}

종토방 게시글 제목:
{titles}

다음 JSON으로 응답:
{{
  "sentiment_score": -1.0 ~ +1.0 사이 실수 (부정=-1, 중립=0, 긍정=+1),
  "dominant_emotion": "공포 또는 탐욕 또는 기대 또는 실망 또는 혼조",
  "summary": "현재 개인투자자 심리 한 줄 요약"
}}
"""
    result = await _call_groq(prompt, system, max_tokens=256)
    try:
        if "```json" in result:
            result = result.split("```json")[1].split("```")[0].strip()
        elif "```" in result:
            result = result.split("```")[1].split("```")[0].strip()
        parsed = json.loads(result)
        parsed["sentiment_score"] = max(-1.0, min(1.0, float(parsed.get("sentiment_score", 0.0))))
        return parsed
    except Exception:
        return {"sentiment_score": 0.0, "dominant_emotion": "혼조", "summary": ""}


# ── 후보 종목 초기 필터링 ──────────────────────────────────────────

async def prefilter_candidates(
    agent_id: str,
    strategy: str,
    candidates: list[dict],
    market_context: dict,
) -> list[dict]:
    """
    Claude 호출 전 Groq으로 후보 종목 사전 필터링
    스코어 상위 20개 → 에이전트 전략에 맞는 10개로 압축

    반환: 필터링된 candidates 리스트 (상위 10개)
    """
    if len(candidates) <= 10:
        return candidates

    candidates_text = json.dumps(candidates[:20], ensure_ascii=False)

    system = "당신은 투자 전략에 맞는 종목을 선별하는 분석가입니다. JSON으로만 응답하세요."
    prompt = f"""
에이전트: {agent_id}
전략: {strategy}

현재 시장 국면 KR: {market_context.get('regime_kr', '횡보')}
현재 시장 국면 US: {market_context.get('regime_us', '횡보')}

후보 종목 (스코어 순):
{candidates_text}

위 후보 중 이 에이전트의 전략에 가장 부합하는 종목 10개의 ticker를 선택하세요.

다음 JSON으로 응답:
{{"selected_tickers": ["ticker1", "ticker2", ...]}}
"""
    result = await _call_groq(prompt, system, max_tokens=256)
    try:
        if "```json" in result:
            result = result.split("```json")[1].split("```")[0].strip()
        elif "```" in result:
            result = result.split("```")[1].split("```")[0].strip()
        parsed = json.loads(result)
        selected = set(parsed.get("selected_tickers", []))
        filtered = [c for c in candidates if c.get("ticker") in selected]
        # 선택 결과가 없으면 원본 상위 10개 반환
        return filtered if filtered else candidates[:10]
    except Exception:
        return candidates[:10]
