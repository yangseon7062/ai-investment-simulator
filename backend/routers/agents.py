from fastapi import APIRouter
from backend.database import fetchall, fetchone
from backend.agents.definitions import get_all_agents, get_agent
from backend.services.scoring import get_top_stocks

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("/")
async def list_agents():
    agents = get_all_agents()
    result = []
    for a in agents:
        port = await fetchone(
            "SELECT cash_krw FROM agent_portfolios WHERE agent_id = $1", (a.agent_id,)
        )
        snap = await fetchone(
            """SELECT total_value_krw, daily_return
               FROM portfolio_snapshots WHERE agent_id = $1
               ORDER BY snapshot_date DESC LIMIT 1""",
            (a.agent_id,),
        )
        positions_count = await fetchone(
            "SELECT COUNT(*) as cnt FROM simulated_trades WHERE agent_id = $1 AND status != 'closed'",
            (a.agent_id,),
        )
        result.append({
            "agent_id": a.agent_id,
            "name_kr": a.name_kr,
            "style": a.style,
            "time_horizon": a.time_horizon,
            "cash_krw": port["cash_krw"] if port else 100_000_000,
            "total_value_krw": snap["total_value_krw"] if snap else 100_000_000,
            "daily_return": snap["daily_return"] if snap else None,
            "total_return": ((snap["total_value_krw"] - 100_000_000) / 100_000_000 * 100) if snap else 0,
            "open_positions": positions_count["cnt"] if positions_count else 0,
        })
    return result


@router.get("/{agent_id}/positions")
async def get_positions(agent_id: str):
    rows = await fetchall(
        """SELECT t.*, c.name, c.sector
           FROM simulated_trades t
           LEFT JOIN company_info c ON t.ticker = c.ticker AND t.market = c.market
           WHERE t.agent_id = $1 AND t.status != 'closed'
           ORDER BY t.trade_date DESC""",
        (agent_id,),
    )
    return [dict(r) for r in rows]


@router.get("/{agent_id}/performance")
async def get_performance(agent_id: str):
    """성과 히스토리 (차트용)"""
    snapshots = await fetchall(
        """SELECT snapshot_date, total_value_krw, daily_return
           FROM portfolio_snapshots WHERE agent_id = $1
           ORDER BY snapshot_date ASC""",
        (agent_id,),
    )
    win_rate = await fetchone(
        """SELECT
             COUNT(*) as total,
             SUM(CASE WHEN was_correct THEN 1 ELSE 0 END) as wins
           FROM postmortems WHERE agent_id = $1""",
        (agent_id,),
    )
    return {
        "snapshots": [dict(r) for r in snapshots],
        "win_rate": round(win_rate["wins"] / win_rate["total"] * 100, 1) if win_rate and win_rate["total"] else None,
    }


@router.get("/stock/{ticker}/matrix")
async def get_stock_matrix(ticker: str):
    """종목별 7개 에이전트 스탠스 매트릭스"""
    agents = get_all_agents()
    result = []
    for a in agents:
        pos = await fetchone(
            """SELECT status, price, trade_date
               FROM simulated_trades
               WHERE agent_id = $1 AND ticker = $2 AND status != 'closed'
               ORDER BY trade_date DESC LIMIT 1""",
            (a.agent_id, ticker),
        )
        last_log = await fetchone(
            """SELECT report_md, thesis, created_at
               FROM investment_logs
               WHERE agent_id = $1 AND tickers = $2
               ORDER BY created_at DESC LIMIT 1""",
            (a.agent_id, ticker),
        )
        result.append({
            "agent_id": a.agent_id,
            "name_kr": a.name_kr,
            "status": pos["status"] if pos else "미보유",
            "price": pos["price"] if pos else None,
            "thesis": last_log["thesis"] if last_log else None,
            "last_updated": last_log["created_at"] if last_log else None,
        })
    return result
