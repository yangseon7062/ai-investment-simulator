from fastapi import APIRouter
from backend.database import fetchall, fetchone
from backend.agents.definitions import get_all_agents, get_agent
from backend.services.scoring import get_top_stocks

router = APIRouter(prefix="/api/agents", tags=["agents"])


def calc_mdd(snapshots: list[dict]) -> dict:
    """
    portfolio_snapshots 리스트에서 MDD 계산
    total_value_krw = 수익률 % (예: 2.5 → +2.5%)
    반환: {
        "mdd": float,          # 최대 낙폭 (예: -12.3)
        "peak": float,         # 고점 수익률
        "current_drawdown": float  # 현재 고점 대비 낙폭
    }
    """
    if not snapshots:
        return {"mdd": 0.0, "peak": 0.0, "current_drawdown": 0.0}

    values = [float(s["total_value_krw"] or 0) for s in snapshots]
    peak = values[0]
    mdd = 0.0
    for v in values:
        if v > peak:
            peak = v
        dd = v - peak
        if dd < mdd:
            mdd = dd

    current = values[-1]
    current_peak = max(values)
    current_drawdown = current - current_peak

    return {
        "mdd": round(mdd, 2),
        "peak": round(current_peak, 2),
        "current_drawdown": round(current_drawdown, 2),
    }


@router.get("/")
async def list_agents():
    agents = get_all_agents()
    result = []
    for a in agents:
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
        all_snaps = await fetchall(
            "SELECT total_value_krw FROM portfolio_snapshots WHERE agent_id = $1 ORDER BY snapshot_date ASC",
            (a.agent_id,),
        )
        mdd_data = calc_mdd([dict(s) for s in all_snaps])
        result.append({
            "agent_id": a.agent_id,
            "name_kr": a.name_kr,
            "style": a.style,
            "time_horizon": a.time_horizon,
            "daily_return": snap["daily_return"] if snap else None,
            "total_return": snap["total_value_krw"] if snap else 0,
            "open_positions": positions_count["cnt"] if positions_count else 0,
            "mdd": mdd_data["mdd"],
            "current_drawdown": mdd_data["current_drawdown"],
            "peak_return": mdd_data["peak"],
        })
    return result


@router.get("/{agent_id}/positions")
async def get_positions(agent_id: str):
    rows = await fetchall(
        """SELECT t.*, c.name, c.sector,
                  s.market_cap AS current_price,
                  CASE WHEN t.price > 0 AND s.market_cap IS NOT NULL
                       THEN ROUND(CAST((s.market_cap - t.price) / t.price * 100 AS NUMERIC), 2)
                       ELSE NULL END AS pnl_pct
           FROM simulated_trades t
           LEFT JOIN company_info c ON t.ticker = c.ticker AND t.market = c.market
           LEFT JOIN stock_scores s ON t.ticker = s.ticker
               AND s.score_date = (SELECT MAX(score_date) FROM stock_scores)
           WHERE t.agent_id = $1 AND t.status != 'closed'
           ORDER BY t.trade_date DESC""",
        (agent_id,),
    )
    return [dict(r) for r in rows]


@router.get("/{agent_id}/performance")
async def get_performance(agent_id: str):
    """성과 히스토리 (차트용) + MDD"""
    snapshots = await fetchall(
        """SELECT snapshot_date, total_value_krw, daily_return
           FROM portfolio_snapshots WHERE agent_id = $1
           ORDER BY snapshot_date ASC""",
        (agent_id,),
    )
    snap_list = [dict(r) for r in snapshots]
    mdd_data = calc_mdd(snap_list)

    win_rate = await fetchone(
        """SELECT
             COUNT(*) as total,
             SUM(CASE WHEN was_correct THEN 1 ELSE 0 END) as wins
           FROM postmortems WHERE agent_id = $1""",
        (agent_id,),
    )
    return {
        "snapshots": snap_list,
        "win_rate": round(win_rate["wins"] / win_rate["total"] * 100, 1) if win_rate and win_rate["total"] else None,
        "mdd": mdd_data["mdd"],
        "peak_return": mdd_data["peak"],
        "current_drawdown": mdd_data["current_drawdown"],
    }


@router.get("/{agent_id}/postmortems")
async def get_postmortems(agent_id: str):
    rows = await fetchall(
        """SELECT id, ticker, pnl_pct, pnl_pct_krw, was_correct, report_md, created_at
           FROM postmortems WHERE agent_id = $1
           ORDER BY created_at DESC LIMIT 20""",
        (agent_id,),
    )
    return [dict(r) for r in rows]


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
