"""
주간 라운드테이블 (금요일 17:00 KST)
"""

from datetime import datetime, timedelta, date
from backend.database import get_db, execute as db_execute
from backend.services.claude_service import generate_roundtable


async def run_roundtable():
    today = date.today()
    week_start = today - timedelta(days=today.weekday())

    async with get_db() as conn:
        weekly_stats = [dict(r) for r in await conn.fetch(
            """SELECT agent_id,
                      SUM(CASE WHEN log_type = 'buy' THEN 1 ELSE 0 END) as buys,
                      SUM(CASE WHEN log_type = 'sell' THEN 1 ELSE 0 END) as sells,
                      SUM(CASE WHEN log_type = 'pass' THEN 1 ELSE 0 END) as passes
               FROM investment_logs
               WHERE created_at >= $1
               GROUP BY agent_id""",
            week_start,
        )]

        # 전략가 포지션 모니터링 (주 1회)
        strategist_positions = [dict(r) for r in await conn.fetch(
            """SELECT t.ticker, t.status, t.price, l.thesis
               FROM simulated_trades t
               LEFT JOIN investment_logs l ON t.log_id = l.id
               WHERE t.agent_id = 'strategist' AND t.status != 'closed'""",
        )]

    summaries = []
    for stat in weekly_stats:
        summaries.append({
            "agent_id": stat["agent_id"],
            "weekly_buys": stat["buys"],
            "weekly_sells": stat["sells"],
            "weekly_passes": stat["passes"],
        })

    if strategist_positions:
        summaries.append({
            "agent_id": "strategist_positions",
            "positions": strategist_positions,
            "note": "전략가 주간 포지션 점검",
        })

    report = await generate_roundtable(summaries)

    await db_execute(
        """INSERT INTO investment_logs (agent_id, log_type, report_md)
           VALUES ('system', 'roundtable', $1)""",
        (report,),
    )
    print("[라운드테이블] 완료")
