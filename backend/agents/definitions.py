"""
7개 AI 에이전트 고정 설정
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
    condition_based: bool = False    # True면 조건 미충족 시 pass (베어, 컨트라리안)
    monitor_daily: bool = True       # False면 주 1회 모니터링 (전략가)
    inverse_etf_only: bool = False   # 베어 전용

    # 데이터 요구사항
    # required_data: 후보 종목이 이 필드를 갖지 않으면 후보에서 제외
    # key_data: 프롬프트에서 강조할 데이터 섹션 (에이전트 전략에 맞는 것만)
    required_data: list = field(default_factory=list)
    key_data: list = field(default_factory=list)


AGENTS: dict[str, AgentConfig] = {

    "macro": AgentConfig(
        agent_id="macro",
        name_kr="매크로",
        style="거시테마형",
        strategy="금리·환율 변화 → 수혜 섹터 로테이션 → 대표 종목 매수",
        time_horizon="1~4주",
        max_positions=4,
        markets=["KR", "US"],
        buy_method="정찰병 (소량 선진입 → 확신 시 추가)",
        sell_method="분할매도",
        max_add_rounds=2,
        trailing_stop_pct=None,
        watch_trigger="거시 환경 변화 신호 1개 감지 (금리·환율 이상 움직임)",
        persona="거시경제 전문가. 큰 그림을 먼저 보고 세부로 내려오는 탑다운 사고. 트렌드와 사이클을 중시.",
        report_style="거시적 시각으로 트렌드 중심 서술. 경제 흐름과 종목의 연결고리를 명확히 설명.",
        report_depth="medium",
        score_weights={"technical": 0.2, "fundamental": 0.3, "sentiment": 0.5},
        required_data=["price"],
        key_data=["fred", "sector_etf", "narrative", "regime", "vix", "exchange_rate"],
    ),

    "strategist": AgentConfig(
        agent_id="strategist",
        name_kr="전략가",
        style="탑다운 퀄리티형",
        strategy="유망 산업 선정 → ROIC·해자 검증된 대형 우량주 발굴 (3년 이상 흑자 필수)",
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
        score_weights={"technical": 0.2, "fundamental": 0.7, "sentiment": 0.1},
        monitor_daily=False,
        required_data=["price", "roic"],  # ROIC 없는 종목은 해자 검증 불가 → 제외
        key_data=["roic", "pbr", "per", "revenue_growth", "sector_etf"],
    ),

    "analyst": AgentConfig(
        agent_id="analyst",
        name_kr="심사역",
        style="가치형",
        strategy="PBR·PER·ROIC 기준 저평가 종목 발굴. 안전마진 확보 우선.",
        time_horizon="4~12주",
        max_positions=5,
        markets=["KR", "US"],
        buy_method="분할매수 + 물타기 (최대 2회)",
        sell_method="분할매도",
        max_add_rounds=2,
        trailing_stop_pct=None,
        watch_trigger="PBR이 목표 밸류에이션 80% 회복 시",
        persona="보수적이고 신중한 가치 투자자. 리스크를 먼저 언급하고 매수 근거를 제시. 숫자에 철저.",
        report_style="리스크를 먼저 언급한 뒤 매수 근거 제시. 보수적 어조 유지. 풀 3단 구조.",
        report_depth="full",
        score_weights={"technical": 0.1, "fundamental": 0.8, "sentiment": 0.1},
        required_data=["price", "pbr"],  # PBR 없으면 저평가 판단 자체가 불가
        key_data=["pbr", "per", "roic", "revenue_growth"],
    ),

    "surfer": AgentConfig(
        agent_id="surfer",
        name_kr="서퍼",
        style="모멘텀형",
        strategy="추세 추종. 강한 모멘텀 + 거래량 급증 + 종토방 확인 → 빠른 진입·이탈.",
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
        key_data=["technical_score", "foreign_net_3d", "institution_net_3d", "pct_from_high", "recent_news"],
    ),

    "explorer": AgentConfig(
        agent_id="explorer",
        name_kr="미래탐색자",
        style="성장형",
        strategy="매출 성장률 20%+ 초기 고성장 중소형주 발굴. 성장 스토리가 핵심.",
        time_horizon="2~8주",
        max_positions=5,
        markets=["KR", "US"],
        buy_method="정찰병",
        sell_method="분할매도",
        max_add_rounds=2,
        trailing_stop_pct=None,
        watch_trigger="매출 성장률 둔화 조짐 또는 성장 스토리 관련 부정 공시",
        persona="비전 중심의 성장 투자자. 미래 가능성을 현재 숫자보다 중시. 스토리텔링을 즐김.",
        report_style="비전과 성장 스토리 중심으로 서술. 숫자는 성장 가능성 입증 도구로 활용.",
        report_depth="medium",
        score_weights={"technical": 0.3, "fundamental": 0.6, "sentiment": 0.1},
        required_data=["price", "revenue_growth"],  # 성장률 없으면 20%+ 검증 불가
        key_data=["revenue_growth", "roic", "recent_news", "pct_from_high"],
    ),

    "contrarian": AgentConfig(
        agent_id="contrarian",
        name_kr="컨트라리안",
        style="역발상형",
        strategy="종토방·VIX·공포탐욕지수 극단 심리 감지 → 군중 반대 방향 역매수.",
        time_horizon="1~3주",
        max_positions=3,
        markets=["KR", "US"],
        buy_method="정찰병 (신중하게)",
        sell_method="일괄매도",
        max_add_rounds=1,
        trailing_stop_pct=None,
        watch_trigger="공포탐욕지수 중립 구간 진입 (심리 정상화 시작)",
        persona="역설적이고 비판적. 군중 심리를 냉소적으로 분석. 모두가 공포일 때 매수.",
        report_style="역설적 표현으로 군중 심리를 비판. 왜 시장이 틀렸는지를 설명.",
        report_depth="medium",
        score_weights={"technical": 0.1, "fundamental": 0.2, "sentiment": 0.7},
        condition_based=True,
        required_data=["price"],  # 심리 지표는 market_context에서 오므로 종목은 가격만 필수
        key_data=["fear_greed", "vix", "regime", "foreign_net_3d", "pct_from_high"],
    ),

    "bear": AgentConfig(
        agent_id="bear",
        name_kr="베어",
        style="하락베팅형",
        strategy="하락 신호 포착 → 인버스 ETF 매수. 상승장에서는 전량 현금 보유.",
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
        key_data=["vix", "fred", "regime", "sector_etf", "narrative"],
    ),
}


def get_agent(agent_id: str) -> AgentConfig:
    if agent_id not in AGENTS:
        raise ValueError(f"Unknown agent: {agent_id}")
    return AGENTS[agent_id]


def get_all_agents() -> list[AgentConfig]:
    return list(AGENTS.values())
