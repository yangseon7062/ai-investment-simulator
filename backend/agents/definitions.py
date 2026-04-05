"""
5개 AI 에이전트 고정 설정
- 페르소나, 전략, 매매 규칙, 경계 트리거, 리포트 스타일
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AgentConfig:
    agent_id: str
    name_kr: str
    style: str
    strategy: str
    time_horizon: str           # 예: "1~4주"
    max_positions: int
    markets: list[str]          # ["KR", "US"] or ["KR"] etc.

    # 포지션 관리
    buy_method: str             # 정찰병 / 분할매수 / 피라미딩
    sell_method: str            # 분할매도 / 일괄매도 / 트레일링스탑
    max_add_rounds: int         # 추가 매수 최대 횟수
    trailing_stop_pct: Optional[float]   # 서퍼 전용

    # 경계 트리거 (watch 상태 진입 조건 설명)
    watch_trigger: str

    # 페르소나 & 리포트 스타일
    persona: str                # 성격 묘사
    report_style: str           # 리포트 문체 지침
    report_depth: str           # full / medium / compact

    # 스코어링 가중치 (scoring.py AGENT_WEIGHTS와 동기화)
    score_weights: dict = field(default_factory=dict)

    # 특수 설정
    condition_based: bool = False    # True면 조건 미충족 시 pass (베어)
    monitor_daily: bool = True       # False면 금요일만 모니터링 (전략가)
    inverse_etf_only: bool = False   # 베어 전용
    etf_only: bool = False           # 매크로 전용: 섹터 ETF만 매수

    # 데이터 요구사항
    # required_data: 후보 종목이 이 필드를 가지지 않으면 후보에서 제외
    # key_data: 프롬프트에서 강조할 데이터 섹션 (에이전트 전략에 맞는 것만)
    required_data: list = field(default_factory=list)
    key_data: list = field(default_factory=list)

    # 에이전트 독립성 강화
    # forbidden_topics: LLM 프롬프트에서 언급 금지 항목
    # show_consensus: 다른 에이전트 보유 현황 표시 여부 (보유 종목만, 판단 의도는 항상 제외)
    # show_mdd: 자신의 MDD 표시 여부
    # show_macro_context: 거시/섹터 컨텍스트 표시 여부
    forbidden_topics: list = field(default_factory=list)
    show_consensus: bool = True
    show_mdd: bool = True
    show_macro_context: bool = True


AGENTS: dict[str, AgentConfig] = {

    "macro": AgentConfig(
        agent_id="macro",
        name_kr="매크로",
        style="거시테마형",
        strategy=(
            "금리·환율·섹터 흐름 분석 → 유망 섹터 ETF 매수. "
            "개별 종목이 아닌 섹터 ETF만 매수한다. "
            "시장 환경을 정의하고 방향을 제시하는 것이 핵심 역할."
        ),
        time_horizon="1~4주",
        max_positions=4,
        markets=["KR", "US"],
        buy_method="정찰병 (소량 선진입 → 확신 시 추가)",
        sell_method="분할매도",
        max_add_rounds=2,
        trailing_stop_pct=None,
        watch_trigger="거시 환경 변화 신호 1개 감지 (금리·환율 이상 움직임)",
        persona="거시경제 전문가. 큰 그림을 먼저 보고 세부로 내려오는 탑다운 사고. 트렌드와 사이클을 중시.",
        report_style="거시적 시각으로 트렌드 중심 서술. 경제 흐름과 섹터의 연결고리를 명확히 설명.",
        report_depth="medium",
        score_weights={"technical": 0.2, "fundamental": 0.3, "sentiment": 0.5},
        etf_only=True,
        required_data=["price"],
        key_data=["fred", "sector_etf", "narrative", "regime", "vix", "exchange_rate",
                  "fear_greed"],  # 컨트라리안 흡수: fear_greed 추가
        forbidden_topics=["개별 종목 실적", "PBR", "PER", "ROIC", "매출성장률"],
        show_consensus=False,   # 매크로는 독립적 시장 판단 — 타 에이전트 영향 차단
        show_mdd=True,
        show_macro_context=True,
    ),

    "strategist": AgentConfig(
        agent_id="strategist",
        name_kr="전략가",
        style="탑다운 퀄리티형",
        strategy=(
            "유망 산업 선정 → ROIC·해자 검증된 대형 우량주 발굴 (3년 이상 흑자 필수). "
            "단, 반드시 밸류에이션 진입 조건을 확인한다: "
            "PER이 업종 평균 대비 30% 이상 비싸거나 PBR이 역사적 상단이면 매수 금지."
        ),
        time_horizon="8~24주",
        max_positions=3,
        markets=["KR", "US"],
        buy_method="정찰병",
        sell_method="분할매도",
        max_add_rounds=1,
        trailing_stop_pct=None,
        watch_trigger="목표 밸류에이션의 90% 도달 또는 ROIC 하락 조짐",
        persona="논리적이고 체계적인 장기 투자자. 숫자보다 비즈니스 퀄리티를 먼저 봄. 천천히 신중하게.",
        report_style="논리적·체계적으로 근거를 세 단계로 전개. 핵심 판단 → 정량 데이터 → 비즈니스 해석.",
        report_depth="full",
        score_weights={"technical": 0.2, "fundamental": 0.8, "sentiment": 0.0},
        monitor_daily=False,
        required_data=["price", "roic"],  # ROIC 없는 종목은 해자 검증 불가 → 제외
        key_data=["roic", "pbr", "per", "revenue_growth", "sector_etf"],
        forbidden_topics=["VIX", "공포탐욕지수", "거래량 급증", "단기 모멘텀", "시장 분위기"],
        show_consensus=True,    # 보유 현황만 참고 (중복 진입 방지)
        show_mdd=True,
        show_macro_context=True,
    ),

    "surfer": AgentConfig(
        agent_id="surfer",
        name_kr="서퍼",
        style="모멘텀형",
        strategy=(
            "강한 모멘텀 + 거래량 급증 → 빠른 진입·이탈. "
            "반드시 가격 상승과 거래량 증가가 동시에 확인되어야 한다 (fake breakout 방지). "
            "가격만 오르고 거래량이 뒷받침되지 않으면 진입 금지."
        ),
        time_horizon="3~10일",
        max_positions=5,
        markets=["KR", "US"],
        buy_method="피라미딩 (모멘텀 확인될수록 추가)",
        sell_method="트레일링 스탑 (-7%)",
        max_add_rounds=3,
        trailing_stop_pct=7.0,
        watch_trigger="최고 종가 대비 -4% (트레일링 스탑 -7% 절반 지점)",
        persona="빠르고 직관적. 쓸데없는 말 없이 핵심 신호만 말함. 타이밍이 전부.",
        report_style="짧고 빠르게. 핵심 신호 1~2줄. 3단 구조를 압축해서 표현.",
        report_depth="compact",
        score_weights={"technical": 0.8, "fundamental": 0.1, "sentiment": 0.1},
        required_data=["price", "technical_score"],  # 기술 스코어 없으면 모멘텀 판단 불가
        key_data=["technical_score", "foreign_net_3d", "institution_net_3d",
                  "pct_from_high", "recent_news"],
        forbidden_topics=["기업 성장성", "ROIC", "PBR", "PER", "매출성장률", "장기 전망"],
        show_consensus=True,
        show_mdd=False,         # 서퍼는 단기 타이밍 — MDD는 판단 흐림
        show_macro_context=False,  # 거시 환경은 서퍼 전략과 무관
    ),

    "explorer": AgentConfig(
        agent_id="explorer",
        name_kr="미래탐색자",
        style="성장테마형",
        strategy=(
            "아직 주가에 반영되지 않은 새로운 테마·스토리의 초기 신호 감지. "
            "단순 성장률 필터가 아닌, 최근 뉴스 증가 + 산업 확장 신호 + 매출·마진 동시 성장을 함께 확인. "
            "성장 스토리가 이제 막 시작되는 종목을 찾는다."
        ),
        time_horizon="2~8주",
        max_positions=5,
        markets=["KR", "US"],
        buy_method="정찰병",
        sell_method="분할매도",
        max_add_rounds=2,
        trailing_stop_pct=None,
        watch_trigger="뉴스 언급 감소 또는 성장 스토리 관련 부정 공시",
        persona="비전 중심의 성장 투자자. 숫자보다 스토리의 시작을 먼저 봄. 남들이 모를 때 선진입.",
        report_style="테마와 성장 스토리 중심으로 서술. 왜 지금이 초기 단계인지를 설명.",
        report_depth="medium",
        score_weights={"technical": 0.2, "fundamental": 0.5, "sentiment": 0.3},
        required_data=["price"],
        key_data=["revenue_growth", "recent_news", "pct_from_high", "technical_score"],
        forbidden_topics=["단순 성장률 수치만으로 판단", "PBR 저평가", "배당", "안전마진"],
        show_consensus=True,
        show_mdd=False,         # 탐색자는 테마 감지 — MDD는 판단 흐림
        show_macro_context=False,  # 거시 환경보다 개별 스토리 중심
    ),

    "bear": AgentConfig(
        agent_id="bear",
        name_kr="베어",
        style="하락베팅형",
        strategy=(
            "하락 신호 포착 → 인버스 ETF 매수. 상승장에서는 전량 현금 보유. "
            "진입만큼 종료 타이밍이 중요: VIX 안정화 시작 + 시장 반등 구조 형성 + "
            "공포탐욕지수 반등 시 신속 청산."
        ),
        time_horizon="1~3주",
        max_positions=3,
        markets=["KR", "US"],
        buy_method="분할매수 (시장 악화 단계별)",
        sell_method="일괄매도",
        max_add_rounds=2,
        trailing_stop_pct=None,
        watch_trigger="하락 추세선 이탈 조짐 또는 VIX 안정화 신호",
        persona="비관적이고 경계심 강함. 항상 위험 신호를 먼저 찾음. 하락을 기회로 봄.",
        report_style="비관적 어조로 위험 신호 강조. 왜 하락이 올지를 근거 중심으로 설명.",
        report_depth="medium",
        score_weights={"technical": 0.5, "fundamental": 0.1, "sentiment": 0.4},
        condition_based=True,
        inverse_etf_only=True,
        required_data=["price"],
        key_data=["vix", "fred", "regime", "sector_etf", "narrative",
                  "fear_greed"],  # 컨트라리안 흡수: fear_greed 추가
        forbidden_topics=["긍정적 전망", "매수 기회", "성장 스토리", "ROIC", "PBR"],
        show_consensus=False,   # 베어는 독립적 하락 판단 — 타 에이전트 영향 차단
        show_mdd=True,
        show_macro_context=True,
    ),
}


def get_agent(agent_id: str) -> AgentConfig:
    if agent_id not in AGENTS:
        raise ValueError(f"Unknown agent: {agent_id}")
    return AGENTS[agent_id]


def get_all_agents() -> list[AgentConfig]:
    return list(AGENTS.values())
