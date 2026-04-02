"""
포지션 모니터링 (16:00 KST KR / 07:30 KST 익일 US)
- 테제 유효성 체크
- 경계/매도 판단
- 매도 시 사후 검증 자동 생성
- 트레일링 스탑 체크 (서퍼)
- 섹터 집중도 경고
"""

from datetime import datetime, date
from backend.database import get_db, execute as db_execute
from backend.services.data_fetcher import get_kr_prices, get_us_prices
from backend.services.claude_service import monitor_position, generate_postmortem
from backend.agents.definitions import get_agent


async def run_position_monitor(market: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {market} 포지션 모니터링 시작")

    async with get_db() as conn:
        positions = [dict(r) for r in await conn.fetch(
            """SELECT t.*, l.report_md as buy_report, l.thesis
               FROM simulated_trades t
               LEFT JOIN investment_logs l ON t.log_id = l.id
               WHERE t.status != 'closed' AND t.market = $1""",
            market,
        )]

    if not positions:
        print(f"  {market} 오픈 포지션 없음")
        return

    tickers = list({p["ticker"] for p in positions})
    if market == "KR":
        prices = await get_kr_prices(tickers)
    else:
        prices = await get_us_prices(tickers)

    today = date.today().isoformat()
    async with get_db() as conn:
        snap_row = await conn.fetchrow(
            "SELECT * FROM market_snapshots WHERE snapshot_date = $1", today
        )
        snapshot = dict(snap_row) if snap_row else {}

    market_context = {
        "regime_kr": snapshot.get("regime_kr", "횡보"),
        "regime_us": snapshot.get("regime_us", "횡보"),
        "narrative": snapshot.get(f"narrative_{market.lower()}", ""),
    }

    from itertools import groupby
    positions.sort(key=lambda x: x["agent_id"])

    for agent_id, agent_positions in groupby(positions, key=lambda x: x["agent_id"]):
        agent_positions = list(agent_positions)
        agent = get_agent(agent_id)

        if not agent.monitor_daily and datetime.now().weekday() != 4:
            continue

        for pos in agent_positions:
            ticker = pos["ticker"]
            price_data = prices.get(ticker)
            if not price_data:
                continue

            current_price = price_data["price"]

            # 트레일링 스탑 체크 (서퍼)
            if agent.trailing_stop_pct and pos.get("highest_price"):
                highest = pos["highest_price"]
                drop_pct = (highest - current_price) / highest * 100
                if drop_pct >= agent.trailing_stop_pct:
                    await _execute_sell(pos, current_price, agent, "트레일링 스탑 발동", market_context)
                    continue

                if current_price > highest:
                    await db_execute(
                        "UPDATE simulated_trades SET highest_price = $1 WHERE id = $2",
                        (current_price, pos["id"]),
                    )

            # Claude 테제 유효성 체크
            result = await monitor_position(
                agent, pos, current_price, market_context, pos.get("thesis", ""),
            )

            new_status = result.get("status", "hold")
            report_md = result.get("report_md", "")
            thesis_valid = result.get("thesis_valid", True)

            await db_execute(
                """INSERT INTO investment_logs
                   (agent_id, log_type, tickers, report_md, thesis_valid,
                    market_regime_kr, market_regime_us)
                   VALUES ($1, 'monitor', $2, $3, $4, $5, $6)""",
                (
                    agent_id, ticker, report_md, thesis_valid,
                    market_context.get("regime_kr"),
                    market_context.get("regime_us"),
                ),
            )

            if new_status == "sell":
                await _execute_sell(pos, current_price, agent, result.get("sell_reason", ""), market_context)
            elif new_status != pos.get("status"):
                await db_execute(
                    "UPDATE simulated_trades SET status = $1 WHERE id = $2",
                    (new_status, pos["id"]),
                )

    await check_sector_concentration()
    print(f"  {market} 모니터링 완료")


async def _execute_sell(position: dict, current_price: float, agent, reason: str, market_context: dict):
    """매도 실행 + 포트폴리오 업데이트 + 사후 검증"""
    agent_id = position["agent_id"]
    ticker = position["ticker"]
    market = position["market"]

    exchange_rate = 1.0
    if market == "US":
        from backend.services.data_fetcher import get_exchange_rate
        exchange_rate = await get_exchange_rate()

    proceeds_krw = current_price * position["quantity"]
    if market == "US":
        proceeds_krw *= exchange_rate

    sell_report = f"## 매도 판단\n\n**사유**: {reason}\n\n**매도가**: {current_price:,.0f}\n"

    await db_execute(
        """INSERT INTO investment_logs
           (agent_id, log_type, tickers, report_md, thesis_valid,
            market_regime_kr, market_regime_us)
           VALUES ($1, 'sell', $2, $3, $4, $5, $6)""",
        (agent_id, ticker, sell_report, False,
         market_context.get("regime_kr"), market_context.get("regime_us")),
    )

    await db_execute(
        "UPDATE simulated_trades SET status = 'closed' WHERE id = $1",
        (position["id"],),
    )

    await db_execute(
        "UPDATE agent_portfolios SET cash_krw = cash_krw + $1, updated_at = NOW() WHERE agent_id = $2",
        (proceeds_krw, agent_id),
    )

    buy_price = position["price"]
    buy_exchange_rate = position.get("exchange_rate") or 1.0
    pnl_pct = (current_price - buy_price) / buy_price * 100
    pnl_pct_krw = pnl_pct
    if market == "US" and buy_exchange_rate > 0:
        buy_krw = buy_price * buy_exchange_rate
        sell_krw = current_price * exchange_rate
        pnl_pct_krw = (sell_krw - buy_krw) / buy_krw * 100

    buy_report = position.get("buy_report") or ""
    holding_days = (datetime.now().date() - datetime.fromisoformat(str(position["trade_date"])[:10]).date()).days

    postmortem_report = await generate_postmortem(
        agent, ticker, position.get("name", ticker),
        buy_report, sell_report, pnl_pct, pnl_pct_krw, holding_days,
    )

    await db_execute(
        """INSERT INTO postmortems
           (agent_id, ticker, buy_log_id, pnl_pct, pnl_pct_krw, was_correct, report_md)
           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
        (agent_id, ticker, position.get("log_id"),
         pnl_pct, pnl_pct_krw, pnl_pct > 0, postmortem_report),
    )


async def check_sector_concentration() -> list[str]:
    """전체 포지션 섹터 집중도 60%+ 경고"""
    async with get_db() as conn:
        rows = [dict(r) for r in await conn.fetch(
            """SELECT t.agent_id, c.sector, COUNT(*) as cnt
               FROM simulated_trades t
               LEFT JOIN company_info c ON t.ticker = c.ticker AND t.market = c.market
               WHERE t.status != 'closed'
               GROUP BY t.agent_id, c.sector""",
        )]

    from collections import defaultdict
    agent_sector = defaultdict(lambda: defaultdict(int))
    agent_total = defaultdict(int)

    for row in rows:
        agent_sector[row["agent_id"]][row["sector"] or "기타"] += row["cnt"]
        agent_total[row["agent_id"]] += row["cnt"]

    warnings = []
    for agent_id, sectors in agent_sector.items():
        total = agent_total[agent_id]
        if total == 0:
            continue
        for sector, cnt in sectors.items():
            if cnt / total >= 0.6:
                warnings.append(f"{agent_id}: {sector} {cnt/total*100:.0f}% 집중")

    return warnings
