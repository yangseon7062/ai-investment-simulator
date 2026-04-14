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
import asyncio
import shutil
from datetime import datetime

from backend.config import CLAUDE_MAX_TOKENS
from backend.database import execute as db_execute

# ── Claude Code CLI 호출 방식 ──
# claude -p 로 비대화형 실행. 웹 검색 포함.
# Groq 롤백 필요 시: git checkout HEAD~1 backend/services/claude_service.py

_CLAUDE_BIN: str | None = None
_CLAUDE_BIN_CHECKED: bool = False


def _get_claude_bin() -> str | None:
    """Claude Code CLI 경로 반환. 없으면 None."""
    global _CLAUDE_BIN, _CLAUDE_BIN_CHECKED
    if not _CLAUDE_BIN_CHECKED:
        _CLAUDE_BIN_CHECKED = True
        found = shutil.which("claude")
        if found:
            _CLAUDE_BIN = found
        else:
            import os
            candidates = [
                os.path.expanduser("~\\AppData\\Roaming\\npm\\claude.cmd"),
                os.path.expanduser("~\\AppData\\Local\\AnthropicClaude\\claude.exe"),
            ]
            for c in candidates:
                if os.path.exists(c):
                    _CLAUDE_BIN = c
                    break
    return _CLAUDE_BIN


async def _call_claude_api(prompt: str, system: str, purpose: str) -> str:
    """Anthropic Python SDK 호출 (claude CLI 없는 환경 fallback — 웹 검색 미지원)."""
    import os
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic 패키지 미설치")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 환경변수 없음")

    client = anthropic.Anthropic(api_key=api_key)

    def _run():
        return client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=CLAUDE_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )

    response = await asyncio.get_event_loop().run_in_executor(None, _run)
    return response.content[0].text


async def _call_claude(prompt: str, system: str, purpose: str) -> str:
    """LLM 호출. claude CLI 있으면 claude -p (웹 검색), 없으면 Anthropic SDK fallback."""
    import subprocess, tempfile, os

    tokens = len(system + prompt) // 4
    print(f"[LLM] purpose={purpose} | 토큰 추정={tokens}")

    claude_bin = _get_claude_bin()

    # Claude CLI 없으면 SDK fallback
    if not claude_bin:
        print(f"[LLM] claude CLI 없음 - Anthropic SDK fallback (웹 검색 미지원)")
        for attempt in range(2):
            try:
                text = await _call_claude_api(prompt, system, purpose)
                print(f"[LLM 응답 미리보기] {text[:300]}")
                return text
            except Exception as e:
                print(f"[LLM/SDK] 시도 {attempt+1} 실패: {e}")
                if attempt == 0:
                    await asyncio.sleep(3)
        print(f"[LLM/SDK] 2회 모두 실패 - pass 처리")
        return ""

    combined = f"{system}\n\n{prompt}"

    async def _run() -> str:
        # 임시 파일에 프롬프트 기록 후 stdin 리다이렉트
        # (Windows pipe 버퍼 문제 및 .cmd 래퍼 stdin 전달 문제 우회)
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        )
        try:
            tmp.write(combined)
            tmp.close()
            with open(tmp.name, "rb") as stdin_file:
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: subprocess.run(
                        ["cmd.exe", "/c", claude_bin, "-p"],
                        stdin=stdin_file,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=180,
                    )
                )
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="ignore").strip()
            stdout_preview = result.stdout.decode("utf-8", errors="ignore").strip()[:200]
            raise RuntimeError(
                f"claude -p 오류 (exit {result.returncode})"
                f" | stderr: {err or '(없음)'}"
                f" | stdout: {stdout_preview or '(없음)'}"
            )
        return result.stdout.decode("utf-8", errors="ignore").strip()

    # 1회 재시도
    for attempt in range(2):
        try:
            text = await _run()
            print(f"[LLM 응답 미리보기] {text[:300].encode('ascii', errors='replace').decode()}")
            return text
        except Exception as e:
            print(f"[Claude/_call_claude] 시도 {attempt+1} 실패: {e}")
            if attempt == 0:
                await asyncio.sleep(5)

    print(f"[Claude/_call_claude] 2회 모두 실패 - pass 처리")
    return ""


# ── 에이전트별 웹 검색 지시 ─────────────────────────────────────────────

_WEB_SEARCH_INSTRUCTIONS = {
    "macro": """
🔍 웹 검색 활용 (판단 전 필수):
- VIX 또는 금리가 큰 폭으로 움직인 경우: 원인을 웹 검색으로 파악하라 (수치만이 아닌 맥락).
- 매수할 섹터 ETF 후보가 있다면: 해당 섹터의 최신 이슈·정책·이벤트를 검색하라.
- watch_trigger(금리·환율·유가·달러 2개 이상 동시 변화) 조건 충족 시: 원인이 일시적인지 구조적인지 확인.
""",
    "strategist": """
🔍 웹 검색 활용 (매수 후보가 있을 때 필수):
- PBR 음수 또는 비정상적 수치: yfinance 이상값인지 실제 재무 이슈인지 교차 확인.
- 최종 매수 후보 확정 전: 해당 기업의 최근 실적 발표일·어닝 서프라이즈 여부 확인 (진입 타이밍 리스크).
- 해자(경쟁 우위)가 실제로 유효한지: 최근 뉴스·공시·경쟁사 동향 확인.
- 반론 검토: "좋은 회사인데 지금 타이밍이 맞는가" — 매수 근거를 반박하는 정보도 검색하라.
""",
    "surfer": """
🔍 웹 검색 활용 (거래량 급등 종목 한정):
- 거래량이 급등한 종목: 단순 수치 확인이 아닌 원인 파악 (공시? 실적? 기관 매수? 뉴스?).
- fake breakout 판단: 거래량 급등 원인이 지속 가능한지 확인.
- 재무·거시 관련 웹 검색은 하지 말 것 (전략 범위 밖).
""",
    "explorer": """
🔍 웹 검색 활용 (테마 유효성 확인):
- 매수 후보의 산업/테마: 지금 실제로 성장 중인지 최신 뉴스·리포트로 확인.
- 성장 스토리가 "지금 시작"인지 "이미 주가에 반영됐는지" 판단: 최근 6개월 주가 흐름 + 애널리스트 커버리지 증가 여부.
""",
    "bear": """
🔍 웹 검색 활용 (하락 트리거 확인):
- 하락 베팅 조건 진입 전: 하락 트리거가 실제로 존재하는지 웹 확인 (뉴스·경제지표·정책).
- 이미 보유 중인 경우: VIX 안정화 신호 + 시장 반등 조짐 검색 → 조기 청산 조건 점검.
""",
}


def _build_web_search_section(agent_id: str) -> str:
    return _WEB_SEARCH_INSTRUCTIONS.get(agent_id, "")


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


def _build_macro_change_context(market_context: dict) -> str:
    """
    5일/20일/3개월 변화율을 LLM이 읽기 좋은 포맷으로 변환
    macro/bear 에이전트에만 주입 (show_macro_context=True인 에이전트)
    """
    changes = market_context.get("changes", {})
    if not changes:
        return ""

    lines = []

    # VIX 변화
    vix_now = market_context.get("vix")
    vix_parts = []
    for suffix, label in [("5d", "5일"), ("20d", "20일"), ("3m", "3개월")]:
        v = changes.get(f"vix_{suffix}")
        if v is not None:
            sign = "+" if v >= 0 else ""
            vix_parts.append(f"{label} {sign}{v:.1f}pt")
    if vix_parts and vix_now:
        lines.append(f"VIX: 현재 {vix_now:.1f} | 변화: {' / '.join(vix_parts)}")

    # 환율 변화
    krw_parts = []
    for suffix, label in [("5d", "5일"), ("20d", "20일"), ("3m", "3개월")]:
        v = changes.get(f"krw_{suffix}_pct")
        if v is not None:
            sign = "+" if v >= 0 else ""
            krw_parts.append(f"{label} {sign}{v:.2f}%")
    if krw_parts:
        lines.append(f"원달러 환율: {' / '.join(krw_parts)}")

    # 금리·스프레드 변화
    fred = market_context.get("fred", {}) or {}
    rate_rows = [
        ("10y_yield", "미국 10년물", fred.get("10Y_YIELD")),
        ("hy_spread", "HY 스프레드",  fred.get("HY_SPREAD")),
        ("ig_spread", "IG 스프레드",  fred.get("IG_SPREAD")),
    ]
    for key, label, current in rate_rows:
        parts = []
        for suffix, slabel in [("5d", "5일"), ("20d", "20일"), ("3m", "3개월")]:
            v = changes.get(f"{key}_{suffix}")
            if v is not None:
                sign = "+" if v >= 0 else ""
                parts.append(f"{slabel} {sign}{v:.3f}%p")
        if parts:
            cur_str = f"현재 {current:.2f}% | " if current is not None else ""
            lines.append(f"{label}: {cur_str}변화: {' / '.join(parts)}")

    if not lines:
        return ""

    return "\n## 📊 거시 지표 변화율 (방향성 판단용)\n" + "\n".join(f"- {l}" for l in lines) + "\n"


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
    recent_wins: list[dict] | None = None,
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

    # 매크로 전용: 구조화 시장 판단 출력 요구
    macro_market_structure_rule = ""
    if agent_config.agent_id == "macro":
        macro_market_structure_rule = """
📋 시장 판단 구조화 출력 규칙 (매크로 필수):
report_md에 반드시 아래 섹션을 포함할 것:

**[시장 상태]** risk-on / risk-off / 중립 중 하나 + 한 줄 이유
**[유리한 전략]** 지금 시장에서 우위에 있는 접근법 (예: 방어 ETF, 현금 비중, 섹터 로테이션)
**[피해야 할 행동]** 지금 하면 안 되는 구체적 행동 (예: 성장주 추격, 레버리지 진입)

→ 이 3개가 없으면 리포트 미완성으로 간주.
"""

    # 미래탐색자 전용: 뉴스 증가율 해석 지침
    explorer_news_trend_section = ""
    if agent_config.agent_id == "explorer":
        explorer_news_trend_section = (
            "\n📰 뉴스 증가율 해석 원칙 (미래탐색자 전용):\n"
            "  - 각 후보에 news_trend 필드가 있으면: 최근 7일 vs 이전 7일 언급 건수 변화율이다.\n"
            "  - news_trend.available=False → 뉴스 증가율 데이터 없음. 언급·사용 금지.\n"
            "  - growth_pct > 50% → 뉴스 모멘텀 상승 중 (성장 스토리 초기 신호 가능성)\n"
            "  - growth_pct < -30% → 뉴스 모멘텀 감소 (스토리 소멸 경계)\n"
            "  - 뉴스 증가율은 단독 매수 근거가 아니다. 매출·마진 추세와 함께 확인할 것.\n"
        )

    # 서퍼 전용: 뉴스 취급 지침
    news_usage_section = ""
    if agent_config.agent_id == "surfer":
        news_usage_section = (
            "\n📰 뉴스 취급 원칙 (서퍼 전용):\n"
            "  - 뉴스는 판단 근거가 아니라 보조 확인 수단이다.\n"
            "  - 매수 근거는 반드시 가격·거래량·기술 지표에서만 도출할 것.\n"
            "  - 뉴스가 좋아도 가격·거래량 신호가 없으면 진입 금지.\n"
            "  - 뉴스가 나빠도 가격·거래량 신호가 강하면 가격이 진실이다.\n"
            "\n📊 수급 데이터 취급 원칙 (서퍼 전용):\n"
            "  - foreign_net_3d(외국인 수급)·institution_net_3d(기관 수급)은 보조 참고 데이터다.\n"
            "  - 수급 데이터가 없어도 기술 스코어·가격·거래량으로 판단 가능하다.\n"
            "  - 수급 없음을 이유로 pass하는 것은 금지. 가격·거래량 신호가 충분하면 매수 가능.\n"
        )

    # 베어 전용: 하락 베팅 진입 논리 강화
    bear_entry_rules = ""
    if agent_config.agent_id == "bear":
        bear_entry_rules = """
⚠️ 베어 에이전트 핵심 원칙 (절대 준수):

당신은 시장 하락에 베팅하는 에이전트다. 일반 투자자와 반대로 생각해야 한다.

✅ 매수 신호 (이 조건들이 보이면 인버스 ETF를 사야 한다):
  - VIX 20 이상 → 시장 공포 확산 중 → 인버스 ETF 매수 우호적
  - 공포탐욕지수 30 이하 → 투자자 심리 극단적 위험 회피 → 하락 모멘텀 지속 가능성
  - 시장 국면 '하락장' 또는 '변동성급등' → 하락 추세 진입 신호

⛔ 절대 금지 판단 오류:
  - "VIX가 높으니 위험하다 → pass" → 틀린 판단. VIX 높음 = 당신의 매수 신호
  - "공포가 극심하니 투자하지 않겠다 → pass" → 틀린 판단. 당신은 공포를 이용해 수익을 낸다
  - "시장이 불안정하니 현금 보유 → pass" → 틀린 판단. 불안정성이 인버스 ETF의 수익원이다

📋 판단 흐름:
  1. 시스템이 당신에게 판단 요청을 보낸 것 = 하락 진입 조건이 이미 코드 레벨에서 확인됨
  2. 당신의 임무는 어느 인버스 ETF를 살지, 얼마나 살지 결정하는 것
  3. 조건이 약하면 hold(다음 조건 명시), 조건이 강하면 buy
  4. pass는 오직 "모든 인버스 ETF 가격 데이터가 없는 경우"만 허용
"""

    # 전략가 전용: 데이터 충분성 기반 판단 규칙
    strategist_data_rules = ""
    if agent_config.agent_id == "strategist":
        strategist_data_rules = """
📊 데이터 충분성 판단 규칙 (전략가 필수 준수):

각 후보 종목에는 아래 플래그가 있다:
  - has_pbr_history: PBR 시계열 4분기 이상 존재 여부
  - has_roic_trend: ROIC 시계열 4분기 이상 존재 여부
  - has_sector_per: 업종 평균 PER/PBR 데이터 존재 여부
  - data_quarters: 보유 분기 수

⛔ 데이터 부족 시 절대 금지 표현:
  - has_pbr_history=False → "역사적 상단/하단", "PBR 밴드" 표현 금지
  - has_roic_trend=False → "ROIC 하락 조짐", "ROIC 추세" 표현 금지
  - has_sector_per=False → "업종 대비 고평가/저평가", "업종 평균 이하" 표현 금지

✅ 데이터 부족 시 대체 기준 (절대 기준 fallback):
  - PBR 역사 없음 → PBR 1.5 이하: 저평가 / 3.0 이상: 고평가 기준으로 판단
  - PER 업종 없음 → PER 15 이하: 저평가 / 25 이상: 고평가 기준으로 판단
  - ROIC 없음(None) → PBR·PER·부채비율로 대체 판단. ROIC 없음을 pass 이유로 사용 금지
  - ROIC 추세 없음 → 현재 ROIC 8% 이상이면 양호, 이하면 추가 검증 필요
  - 금융/보험/은행 업종은 ROIC 대신 PBR 1.0 이하 + PER 10 이하를 우량 기준으로 판단

📋 리포트 작성 시 반드시 명시:
  - 역사 데이터 사용 시: "(역사 비교: {data_quarters}분기 시계열 기반)"
  - 절대 기준 사용 시: "(절대 기준 사용: 역사 비교 데이터 부족)"
  - 업종 데이터 사용 시: "(업종 중앙값 {sector_median_per} 대비)"
  - 업종 데이터 없을 시: "(업종 비교 불가: 절대 기준 사용)"

📊 PBR 밴드 해석 규칙 (전략가 필수):
각 후보에는 pbr_band 필드가 있을 수 있다:
  - pbr_band_available=False → "PBR 역사 밴드 부족 (데이터 {data_quarters}분기 미만)" 명시, 밴드 기반 판단 금지
  - pbr_band_available=True → pbr_band.percentile 기준으로 해석:
      * percentile ≤ 20: 역사적 저점 구간 → 진입 우호적
      * percentile ≥ 80: 역사적 고점 구간 → 진입 위험, 원칙적 금지
      * 20 < percentile < 80: 중간 구간 → ROIC·FCF 등 질적 요소로 판단
  - pbr_band_caution=True → "⚠️ 금융/보험/리츠 섹터 — PBR 해석 시 업종 자본 구조 특성 고려 필수" 명시
  - PBR 밴드는 보조지표: ROIC → gross_margin → FCF → 부채비율 확인 후 마지막에 참고
  - 리포트에 pbr_band.percentile이 있으면: "(역사 밴드 하위 {percentile}% 구간, {quarters}분기 기준)" 형식으로 명시
"""

    web_search_section = _build_web_search_section(agent_config.agent_id)

    system = f"""당신은 '{agent_config.name_kr}'라는 AI 투자 에이전트입니다.
페르소나: {agent_config.persona}
전략: {agent_config.strategy}
투자 시간축: {agent_config.time_horizon}
리포트 스타일: {agent_config.report_style}
{macro_lens}{key_data_section}{forbidden_section}{macro_market_structure_rule}{explorer_news_trend_section}{news_usage_section}{bear_entry_rules}{strategist_data_rules}{web_search_section}
모든 판단은 한국어로 작성하세요.
전문 용어 사용 시 반드시 괄호로 설명을 추가하세요. (예: PBR(주가순자산비율))
숫자 근거는 반드시 의미 해석을 포함하세요.

⚠️ 데이터 누락 처리 원칙:
- "⚠️없음"으로 표시된 항목은 데이터가 수집되지 않은 것이다. 해당 항목을 투자 근거로 사용하지 말 것.
- data_gaps 필드가 있는 종목은 누락 데이터를 리포트에 명시할 것.
- 당신의 required_data(핵심 판단 데이터)가 "⚠️없음"인 종목은 pass 처리할 것.
- key_data는 있으면 참고하는 추가 정보다. key_data가 없어도 required_data가 있으면 판단 가능.
- 숫자 값(pbr, per, roic 등)이 실제로 존재하면 "데이터 없음"이라고 말하는 것은 금지. 있는 데이터로 판단하라.

📋 판단 구조 규칙:
- hold(관망): 관심 종목이 있으나 아직 진입 조건 미충족 — 추후 재검토 예정
- pass: 오늘 이 전략 기준으로 적합한 종목 자체가 없음 — 당분간 재검토 불필요

⚠️ pass 원칙 (매우 중요):
- 후보 20개가 있어도 조건 미달이면 pass가 정답이다. 뭔가 골라야 한다는 압박을 느끼지 말 것.
- "후보 중 그나마 나은 것"을 고르는 것은 금지. 전략 기준을 충족하는 종목이 없으면 pass.
- 확신이 없으면 pass. 애매한 buy보다 명확한 pass가 훨씬 낫다."""

    # Plan B: 거시 컨텍스트 허용 에이전트만 — 임계값 초과 시 동적 경고 주입
    # show_macro_context=False(서퍼·탐색자)는 거시 경고도 차단 (독립성 유지)
    warning_context = _build_market_warning_context(market_context) if agent_config.show_macro_context else ""

    # 거시 지표 변화율 (macro/bear/strategist 전용 — show_macro_context=True인 에이전트)
    macro_change_section = ""
    if agent_config.show_macro_context:
        macro_change_section = _build_macro_change_context(market_context)

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

    # 최근 손절 내역 섹션
    loss_section = ""
    if recent_losses:
        loss_lines = []
        for l in recent_losses:
            line = f"- {l.get('ticker')} {l.get('pnl_pct', 0):+.1f}% ({l.get('created_at', '')[:10]})"
            if l.get("failure_summary"):
                line += f"\n  → 실패 요약: {l['failure_summary'][:150]}"
            loss_lines.append(line)
        loss_section = (
            f"\n## 최근 30일 손절 내역 + 실패 유형 (반드시 참고)\n"
            + "\n".join(loss_lines)
            + "\n⚠️ 위와 같은 실패 패턴을 이번 판단에서 반복하지 말 것. 위 종목 재진입 시 신중하게 판단할 것.\n"
        )

    # 최근 수익 내역 섹션 (성공 패턴 학습)
    win_section = ""
    if recent_wins:
        win_lines = []
        for w in recent_wins:
            line = f"- {w.get('ticker')} {w.get('pnl_pct', 0):+.1f}% ({w.get('created_at', '')[:10]})"
            if w.get("win_summary"):
                line += f"\n  → 성공 요약: {w['win_summary'][:150]}"
            win_lines.append(line)
        win_section = (
            f"\n## 최근 90일 수익 사례 (성공 패턴 참고)\n"
            + "\n".join(win_lines)
            + "\n💡 위 성공 사례에서 어떤 조건이 맞아떨어졌는지 이번 판단에 참고할 것.\n"
        )

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

    # 에이전트 전략과 무관한 heavy 필드 제거 (TPM 절약)
    # prices_60d: 항상 제거 (raw 배열, LLM 해석 불가)
    # 에이전트별 추가 제거:
    #   surfer  → 재무·뉴스 계열 전부 (key_data가 기술 지표만)
    #   bear    → 재무·뉴스 계열 전부 (인버스 ETF만, 개별 재무 불필요)
    #   macro   → 재무·뉴스 계열 전부 (섹터 ETF만, 개별 재무 불필요)
    _ALWAYS_STRIP = {"prices_60d"}
    _FUNDAMENTAL_FIELDS = {
        "recent_news", "financials_history", "pbr_band", "news_trend",
        "roic", "pbr", "per", "revenue_growth", "gross_margin",
        "fcf", "debt_ratio", "invested_capital", "operating_income",
        "net_income", "total_assets", "revenue",
    }
    _STRIP_FUNDAMENTAL_AGENTS = {"surfer", "bear", "macro"}
    # 전략가·탐색자: raw 재무제표는 제거, 파생 지표(roic/pbr/per 등)만 유지
    _RAW_FINANCIALS = {
        "revenue", "operating_income", "net_income",
        "total_assets", "invested_capital",
        "financials_history", "pbr_band", "news_trend",
        "recent_news",  # 전략가/탐색자는 ROIC·PBR 중심 — 뉴스 원문 불필요
    }
    _STRIP_RAW_AGENTS = {"strategist", "explorer"}

    def _clean_candidate(c: dict) -> dict:
        strip = set(_ALWAYS_STRIP)
        if agent_config.agent_id in _STRIP_FUNDAMENTAL_AGENTS:
            strip |= _FUNDAMENTAL_FIELDS
        if agent_config.agent_id in _STRIP_RAW_AGENTS:
            strip |= _RAW_FINANCIALS
        return {k: v for k, v in c.items() if k not in strip}

    # 전략가/미래탐색자는 후보 10개로 제한 (TPM 절약)
    # 나머지 에이전트는 20개
    _MAX_CANDIDATES = 10 if agent_config.agent_id in {"strategist", "explorer"} else 20
    cleaned_candidates = [_clean_candidate(c) for c in candidate_stocks[:_MAX_CANDIDATES]]

    macro_verdict_section = ""
    if market_context.get("macro_verdict"):
        macro_verdict_section = f"\n## 매크로 에이전트 선행 판단\n{market_context['macro_verdict']}\n"

    prompt = f"""
## 현재 시장 상황 (거시 수치)
국면: KR={market_context.get('regime_kr')} / US={market_context.get('regime_us')}
VIX: {market_context.get('vix')} | 공포탐욕지수: {market_context.get('fear_greed')}
FRED 금리: {json.dumps(market_context.get('fred', {}), ensure_ascii=False)}
gold 변화: {market_context.get('gold_change_pct', 0):+.1f}% | S&P500 변화: {market_context.get('spx_change_pct', 0):+.1f}%
{macro_change_section}{macro_verdict_section}{extra_section}{narrative_section}{warning_context}{loss_section}{win_section}
## 보유 포지션 ({len(current_positions)}개) — 현재 수익률 포함
{json.dumps(pos_summary, ensure_ascii=False, indent=2)}

## 후보 종목 (스코어 상위 + 거래량 급등 포함)
{json.dumps(cleaned_candidates, ensure_ascii=False, indent=2)}

## 최근 30일 내 판단 기록
{json.dumps(recent_logs, ensure_ascii=False, indent=2)}

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
  "report_md": "## [{agent_config.name_kr}] 오늘의 판단\\n\\n**[결론]** buy/hold/pass\\n\\n**[이유]** 이 전략 기준 2~3개 근거만\\n\\n**[행동]** 지금 할 행동 구체적으로\\n\\n**[다음 조건]** 언제 다시 볼지\\n\\n**[리스크]** 틀릴 수 있는 이유\\n\\n**[후보 비교]** buy일 때만: 왜 이 종목이고 다른 상위 후보는 왜 탈락했는지 2~3개 간략 비교 (pass/hold면 생략)",
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

    # Plan B: 거시 컨텍스트 허용 에이전트만 경고 주입 (서퍼·탐색자 차단)
    warning_context = _build_market_warning_context(market_context) if agent_config.show_macro_context else ""

    pnl_pct = (current_price - position["price"]) / position["price"] * 100

    # 급락 감지 정보 (price_spikes가 market_context에 있을 경우)
    spike_note = ""
    spike_pct = market_context.get("price_spikes", {}).get(position.get("ticker", ""), None)
    if spike_pct is not None:
        spike_note = f"\n⚠️ **오늘 급락 감지: {spike_pct:+.1f}%** — 즉각적 테제 재검토 필요"

    # 최신 뉴스 섹션 — 서퍼는 뉴스 판단 근거 사용 금지
    news_list = position.get("recent_news", [])
    news_section = ""
    if agent_config.agent_id != "surfer":
        if news_list:
            news_section = "\n## 최신 종목 뉴스\n" + "\n".join(f"- {n}" for n in news_list) + "\n"
        else:
            news_section = "\n## 최신 종목 뉴스\n- ⚠️없음 (뉴스 수집 실패 또는 없음)\n"

    # show_macro_context=False 에이전트는 VIX/공포탐욕 미표시
    if agent_config.show_macro_context:
        market_section = f"""## 현재 시장 상황
국면: KR={market_context.get('regime_kr')} / US={market_context.get('regime_us')}
VIX: {market_context.get('vix')} | 공포탐욕지수: {market_context.get('fear_greed')}
{warning_context}"""
    else:
        market_section = f"""## 현재 시장 상황
국면: KR={market_context.get('regime_kr')} / US={market_context.get('regime_us')}"""

    # 서퍼는 테제 개념 없음 — 기술 신호 기반 점검
    if agent_config.agent_id == "surfer":
        thesis_line = f"매수 신호 근거: {original_thesis}"
        judgment_instruction = "이 포지션의 기술적 신호(가격 모멘텀, 거래량)가 아직 유효한지 판단하세요. 테제나 펀더멘털은 언급하지 마세요."
    else:
        thesis_line = f"매수 테제: {original_thesis}"
        judgment_instruction = "이 포지션의 투자 테제가 아직 유효한지 판단하세요."

    prompt = f"""
## 보유 포지션
종목: {position.get('name', position['ticker'])} ({position['ticker']})
매수가: {position['price']:,.0f}
현재가: {current_price:,.0f}
수익률: {pnl_pct:+.2f}%
보유 기간: {holding_days}일
{thesis_line}
현재 상태: {position.get('status', 'hold')}{spike_note}
{news_section}
{market_section}
---

{judgment_instruction}

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
    """사후 검증 리포트 생성 (웹 검색으로 실제 결과 확인 포함)"""
    outcome = "수익" if pnl_pct > 0 else "손실"

    system = f"""당신은 '{agent_config.name_kr}' AI 에이전트입니다.
자신의 투자 결정을 솔직하게 회고하세요. 맞았으면 왜 맞았는지, 틀렸으면 왜 틀렸는지.

🔍 웹 검색 활용 (사후 분석 필수):
- {ticker}({name})의 최근 주가 흐름·실적·뉴스를 검색해 매도 후 실제로 어떻게 됐는지 확인하라.
- {'손실 원인' if pnl_pct < 0 else '수익 요인'}이 매수 당시 리포트에서 예측 가능했는지 판단하라.
- 같은 조건이 다시 오면 어떻게 대응해야 하는지 구체적 기준을 제시하라."""

    prompt = f"""
## 종료된 포지션
종목: {name} ({ticker})
결과: {outcome} {pnl_pct:+.2f}% (환율 반영 원화 실질: {pnl_pct_krw:+.2f}%)
보유 기간: {holding_days}일

## 매수 당시 리포트
{buy_report}

## 매도 당시 리포트
{sell_report}

---

위 정보 + 웹 검색 결과를 바탕으로 사후 검증하세요:

1. **결과 확인**: 매도 후 {ticker} 주가가 실제로 어떻게 됐나? (웹 검색)
2. **판단 평가**: 왜 맞았나 / 왜 틀렸나 — 매수 테제가 실제로 맞았는지
3. **놓친 신호**: 당시 리포트에서 놓쳤거나 과소평가한 리스크
4. **재발 방지**: 같은 상황이 다시 오면 어떤 기준으로 다르게 판단할 것인가

마크다운 형식으로 작성. 한국어.
"""
    return await _call_claude(prompt, system, f"postmortem_{agent_config.agent_id}")


# ── 주간 라운드테이블 ──────────────────────────────────────────────

async def generate_roundtable(agents_summaries: list[dict]) -> str:
    """5개 에이전트 주간 요약 → 라운드테이블 토론 리포트"""
    system = "당신은 5명의 AI 투자자가 참여하는 주간 투자 토론의 진행자입니다."
    prompt = f"""
다음은 이번 주 5개 AI 에이전트(매크로·전략가·서퍼·미래탐색자·베어)의 투자 요약입니다:

{json.dumps(agents_summaries, ensure_ascii=False, indent=2)}

이를 바탕으로 주간 라운드테이블 토론 리포트를 작성하세요:
1. 각 에이전트의 이번 주 핵심 판단 요약
2. 에이전트 간 의견 충돌·합의 분석 (특히 R 상승 대응 방식의 차이)
3. 다음 주 시장 전망 (5개 시각 통합, R-G 균형 관점 포함)

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
    """같은 종목 반대 포지션 → 토론 리포트 (요약 블록 포함)"""
    system = "당신은 두 AI 투자자의 상반된 의견을 분석하는 중립적 분석가입니다."
    prompt = f"""
종목: {name} ({ticker})

## {bull_agent} (매수 측)
{bull_report}

## {bear_agent} (매도/회의 측)
{bear_report}

---

두 의견을 분석하고 아래 형식으로 토론 리포트를 작성하세요.

**반드시 리포트 맨 앞에 아래 요약 블록을 먼저 작성하고, 그 다음 상세 분석을 이어서 작성하세요:**

## 📋 요약
- **종목**: {name} ({ticker})
- **대립 구도**: {bull_agent}(매수) vs {bear_agent}(매도/회의)
- **핵심 쟁점**: (한 줄 — 무엇이 핵심 의견 차이인지)
- **결론**: (한 줄 — 어떤 조건이 되면 누가 맞을지)

---

## 상세 분석
1. 핵심 논거 비교 (성장(G) vs 할인율(R) 관점 포함)
2. 각각의 설득력 평가
3. 어떤 조건이 충족되면 누가 맞을지 (금리 방향, 이익 반응 등)

마크다운 형식. 한국어. 초보자도 이해하기 쉽게.
"""
    return await _call_claude(prompt, system, f"debate_{ticker}")


# ── 오늘의 한 줄 요약 ──────────────────────────────────────────────

async def generate_daily_summary(agents_decisions: list[dict]) -> str:
    """5개 에이전트 오늘 판단 → 한 줄 요약"""
    system = "한 문장으로 오늘 AI 투자자들의 전체 분위기를 요약하세요."
    prompt = f"""
오늘 5개 AI 에이전트(매크로·전략가·서퍼·미래탐색자·베어)의 투자 결정:
{json.dumps(agents_decisions, ensure_ascii=False, indent=2)}

위 내용을 한 문장(40자 이내)으로 요약하세요. 한국어.
예: "금리 불확실성 속 반도체 분할매수 우세, 베어는 현금 대기."
"""
    return await _call_claude(prompt, system, "daily_summary")
