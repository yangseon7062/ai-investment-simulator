"""
에이전트 병렬 실행 오케스트레이터 (08:30 KST)
1. 7개 에이전트 병렬 실행
2. 전원 완료 대기
3. 충돌 감지 → 토론 리포트
4. portfolio_snapshots 기록
5. 오늘의 한 줄 요약 생성
"""

import asyncio
import json
from datetime import datetime, date
from backend.agents.definitions import get_all_agents, get_agent
from backend.services.scoring import get_top_stocks
from backend.services.claude_service import (
    generate_agent_decision,
    generate_debate,
    generate_daily_summary,
)
from backend.database import get_db, execute as db_execute
from backend.services.data_fetcher import get_exchange_rate
from backend.services.groq_service import prefilter_candidates


async def run_single_agent(agent_config, market_context: dict) -> dict:
    """단일 에이전트 실행"""
    agent_id = agent_config.agent_id
    print(f"  [{agent_id}] 시작")

    # 현금 잔고
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT cash_krw FROM agent_portfolios WHERE agent_id = $1", agent_id
        )
        cash_krw = row["cash_krw"] if row else 100_000_000.0

    # 보유 포지션
    async with get_db() as conn:
        rows = await conn.fetch(
            """SELECT t.*, c.name, c.sector
               FROM simulated_trades t
               LEFT JOIN company_info c ON t.ticker = c.ticker AND t.market = c.market
               WHERE t.agent_id = $1 AND t.status != 'closed'""",
            agent_id,
        )
        positions = [dict(r) for r in rows]

    # 최대 종목 수 체크
    if len(positions) >= agent_config.max_positions:
        return {"agent_id": agent_id, "decision": "pass", "reason": "최대 종목 수 도달"}

    # 조건 기반 에이전트 (베어, 컨트라리안) — 조건 체크
    if agent_config.condition_based:
        if not await _check_entry_condition(agent_config, market_context):
            await _save_pass_log(agent_id, "진입 조건 미충족", market_context)
            return {"agent_id": agent_id, "decision": "pass", "reason": "조건 미충족"}

    # 최근 30일 로그 (에이전트 메모리)
    async with get_db() as conn:
        rows = await conn.fetch(
            """SELECT log_type, tickers, thesis, created_at
               FROM investment_logs
               WHERE agent_id = $1 AND created_at > NOW() - INTERVAL '30 days'
               ORDER BY created_at DESC LIMIT 20""",
            agent_id,
        )
        recent_logs = [dict(r) for r in rows]

    # 스코어 상위 종목 (KR + US)
    kr_candidates, us_candidates = await asyncio.gather(
        get_top_stocks(agent_id, "KR", top_n=20),
        get_top_stocks(agent_id, "US", top_n=20),
    )
    candidates = kr_candidates + us_candidates

    # 베어는 인버스 ETF만
    if agent_config.inverse_etf_only:
        from backend.config import INVERSE_ETFS
        candidates = [
            {"ticker": v, "name": k, "market": "KR" if k.startswith("KR") else "US", "agent_score": 80}
            for k, v in INVERSE_ETFS.items()
        ]
    else:
        # Groq: Claude 호출 전 후보 종목 사전 필터링 (40개 → 10개)
        candidates = await prefilter_candidates(
            agent_id, agent_config.strategy, candidates, market_context
        )

    # Claude 투자 판단
    decision = await generate_agent_decision(
        agent_config,
        market_context,
        candidates,
        positions,
        recent_logs,
        cash_krw,
    )

    # 결과 처리
    if decision.get("decision") == "buy" and decision.get("ticker"):
        await _execute_buy(agent_id, agent_config, decision, cash_krw)
    else:
        await _save_pass_log(agent_id, decision.get("pass_reason", "관망"), market_context, decision.get("report_md"))

    print(f"  [{agent_id}] 완료 → {decision.get('decision')} {decision.get('ticker', '')}")
    return {"agent_id": agent_id, **decision}


async def _check_entry_condition(agent_config, market_context: dict) -> bool:
    """베어·컨트라리안 진입 조건 체크"""
    if agent_config.agent_id == "bear":
        regime_kr = market_context.get("regime_kr", "횡보")
        regime_us = market_context.get("regime_us", "횡보")
        return "하락" in regime_kr or "하락" in regime_us or "변동성" in regime_kr or "변동성" in regime_us

    if agent_config.agent_id == "contrarian":
        fg = market_context.get("fear_greed", {})
        value = fg.get("value", 50) if isinstance(fg, dict) else 50
        return value <= 25 or value >= 75

    return True


async def _execute_buy(agent_id: str, agent_config, decision: dict, cash_krw: float):
    """매수 실행"""
    ticker = decision["ticker"]
    market = decision.get("market", "KR")
    price = decision.get("price", 0)
    quantity = decision.get("quantity", 0)
    thesis = decision.get("thesis", "")
    report_md = decision.get("report_md", "")

    if price <= 0 or quantity <= 0:
        return

    exchange_rate = 1.0
    if market == "US":
        exchange_rate = await get_exchange_rate()

    cost_krw = price * quantity * (exchange_rate if market == "US" else 1.0)

    # 현금 부족 시
    if cost_krw > cash_krw:
        await _handle_cash_shortage(agent_id, agent_config, cost_krw, cash_krw)
        async with get_db() as conn:
            row = await conn.fetchrow(
                "SELECT cash_krw FROM agent_portfolios WHERE agent_id = $1", agent_id
            )
            cash_krw = row["cash_krw"] if row else 0
        if cost_krw > cash_krw:
            await _save_pass_log(agent_id, "현금 부족", {}, report_md)
            return

    # 로그 저장 + log_id 획득 (RETURNING id)
    async with get_db() as conn:
        log_id = await conn.fetchval(
            """INSERT INTO investment_logs
               (agent_id, log_type, tickers, report_md, thesis)
               VALUES ($1, 'buy', $2, $3, $4)
               RETURNING id""",
            agent_id, ticker, report_md, thesis,
        )

    # 매수 기록
    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO simulated_trades
               (agent_id, ticker, market, name, action, price, quantity,
                exchange_rate, log_id, highest_price, status)
               VALUES ($1, $2, $3, $4, 'BUY', $5, $6, $7, $8, $9, 'buy')""",
            agent_id, ticker, market,
            decision.get("name", ticker),
            price, quantity, exchange_rate,
            log_id, price,
        )

    # 현금 차감
    await db_execute(
        "UPDATE agent_portfolios SET cash_krw = cash_krw - $1, updated_at = NOW() WHERE agent_id = $2",
        (cost_krw, agent_id),
    )


async def _handle_cash_shortage(agent_id: str, agent_config, needed: float, available: float):
    """현금 부족 시 가장 약한 포지션 청산"""
    if agent_id in ("strategist", "analyst"):
        return

    async with get_db() as conn:
        weakest = await conn.fetchrow(
            """SELECT id, ticker, market, price, quantity, exchange_rate
               FROM simulated_trades
               WHERE agent_id = $1 AND status = 'watch'
               ORDER BY trade_date ASC LIMIT 1""",
            agent_id,
        )

    if not weakest:
        return

    from backend.services.data_fetcher import get_kr_prices, get_us_prices
    ticker = weakest["ticker"]
    market = weakest["market"]

    if market == "KR":
        prices = await get_kr_prices([ticker])
    else:
        prices = await get_us_prices([ticker])

    current_price = prices.get(ticker, {}).get("price", weakest["price"])
    exchange_rate = 1.0
    if market == "US":
        exchange_rate = await get_exchange_rate()

    proceeds = current_price * weakest["quantity"] * (exchange_rate if market == "US" else 1.0)

    await db_execute(
        "UPDATE simulated_trades SET status = 'closed' WHERE id = $1",
        (weakest["id"],),
    )
    await db_execute(
        "UPDATE agent_portfolios SET cash_krw = cash_krw + $1 WHERE agent_id = $2",
        (proceeds, agent_id),
    )


async def _save_pass_log(agent_id: str, reason: str, market_context: dict, report_md: str = None):
    """관망 로그 저장"""
    md = report_md or f"## 관망\n\n**사유**: {reason}"
    await db_execute(
        """INSERT INTO investment_logs
           (agent_id, log_type, report_md, market_regime_kr, market_regime_us)
           VALUES ($1, 'pass', $2, $3, $4)""",
        (
            agent_id, md,
            market_context.get("regime_kr"),
            market_context.get("regime_us"),
        ),
    )


# ── 후처리: 충돌 감지 + 요약 ──────────────────────────────────────

async def detect_conflicts_and_debate(decisions: list[dict]):
    """같은 종목 반대 포지션 감지 → 토론 리포트"""
    today = date.today()
    async with get_db() as conn:
        today_logs = [dict(r) for r in await conn.fetch(
            """SELECT agent_id, tickers, report_md, log_type FROM investment_logs
               WHERE log_type IN ('buy', 'sell') AND DATE(created_at) = $1""",
            today,
        )]

    buy_agents: dict[str, dict] = {}
    sell_agents: dict[str, dict] = {}

    for log in today_logs:
        ticker = log.get("tickers", "")
        if log["log_type"] == "buy":
            buy_agents[ticker] = log
        elif log["log_type"] == "sell":
            sell_agents[ticker] = log

    for ticker in set(buy_agents) & set(sell_agents):
        bull = buy_agents[ticker]
        bear = sell_agents[ticker]
        debate_report = await generate_debate(
            ticker, ticker,
            bull["agent_id"], bull["report_md"],
            bear["agent_id"], bear["report_md"],
        )
        await db_execute(
            """INSERT INTO investment_logs
               (agent_id, log_type, tickers, report_md)
               VALUES ('system', 'debate', $1, $2)""",
            (ticker, debate_report),
        )


async def save_portfolio_snapshots(exchange_rate: float):
    """모든 에이전트 포트폴리오 일별 스냅샷 저장"""
    today = date.today()

    for agent in get_all_agents():
        agent_id = agent.agent_id
        async with get_db() as conn:
            port_row = await conn.fetchrow(
                "SELECT cash_krw FROM agent_portfolios WHERE agent_id = $1", agent_id
            )
            cash = port_row["cash_krw"] if port_row else 100_000_000.0

            positions = [dict(r) for r in await conn.fetch(
                """SELECT ticker, market, quantity, price
                   FROM simulated_trades
                   WHERE agent_id = $1 AND status != 'closed'""",
                agent_id,
            )]

        stock_value = sum(
            p["price"] * p["quantity"] * (exchange_rate if p["market"] == "US" else 1.0)
            for p in positions
        )
        total = cash + stock_value

        async with get_db() as conn:
            prev_row = await conn.fetchrow(
                """SELECT total_value_krw FROM portfolio_snapshots
                   WHERE agent_id = $1 ORDER BY snapshot_date DESC LIMIT 1""",
                agent_id,
            )

        daily_return = None
        if prev_row and prev_row["total_value_krw"]:
            daily_return = (total - prev_row["total_value_krw"]) / prev_row["total_value_krw"] * 100

        await db_execute(
            """INSERT INTO portfolio_snapshots
               (agent_id, snapshot_date, cash_krw, stock_value_krw, total_value_krw, daily_return)
               VALUES ($1, $2, $3, $4, $5, $6)
               ON CONFLICT (agent_id, snapshot_date) DO UPDATE SET
                 cash_krw = EXCLUDED.cash_krw,
                 stock_value_krw = EXCLUDED.stock_value_krw,
                 total_value_krw = EXCLUDED.total_value_krw,
                 daily_return = EXCLUDED.daily_return""",
            (agent_id, today, cash, stock_value, total, daily_return),
        )


# ── 메인 실행 ──────────────────────────────────────────────────────

async def run_all_agents():
    """08:30 KST 전체 에이전트 실행"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 에이전트 실행 시작")

    today = date.today()
    async with get_db() as conn:
        snapshot = dict(await conn.fetchrow(
            "SELECT * FROM market_snapshots WHERE snapshot_date = $1", today
        ) or {})

    macro_raw = snapshot.get("macro_data", "{}")
    macro_data = json.loads(macro_raw) if isinstance(macro_raw, str) else macro_raw

    market_context = {
        "regime_kr": snapshot.get("regime_kr", "횡보"),
        "regime_us": snapshot.get("regime_us", "횡보"),
        "narrative_kr": snapshot.get("narrative_kr", ""),
        "narrative_us": snapshot.get("narrative_us", ""),
        "fear_greed": macro_data.get("fear_greed", {}),
        "vix": macro_data.get("vix", 20),
        "fred": macro_data.get("fred", {}),
        "gold_drop": macro_data.get("gold_drop", False),
        "equity_drop": macro_data.get("equity_drop", False),
        "gold_change_pct": macro_data.get("gold_change_pct", 0.0),
        "spx_change_pct": macro_data.get("spx_change_pct", 0.0),
        "date": today,
    }

    agents = get_all_agents()
    tasks = [run_single_agent(agent, market_context) for agent in agents]
    decisions = await asyncio.gather(*tasks, return_exceptions=True)
    decisions = [d for d in decisions if isinstance(d, dict)]

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 후처리 시작")

    exchange_rate = await get_exchange_rate()

    await detect_conflicts_and_debate(decisions)
    await save_portfolio_snapshots(exchange_rate)

    summary_input = [
        {"agent": d.get("agent_id"), "decision": d.get("decision"), "ticker": d.get("ticker"), "thesis": d.get("thesis")}
        for d in decisions
    ]
    daily_summary = await generate_daily_summary(summary_input)

    await db_execute(
        "UPDATE market_snapshots SET daily_summary = $1 WHERE snapshot_date = $2",
        (daily_summary, today),
    )

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 완료 — {daily_summary}")
    return decisions
