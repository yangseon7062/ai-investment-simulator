from fastapi import APIRouter
from backend.database import fetchall, fetchone

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
async def get_summary():
    """메인 대시보드 — 오늘 요약 + 국면 + 에이전트 성과"""
    today_snap = await fetchone(
        "SELECT * FROM market_snapshots ORDER BY snapshot_date DESC LIMIT 1"
    )
    agents_perf = await fetchall(
        """SELECT p.agent_id,
                  p.total_value_krw,
                  p.daily_return,
                  (p.total_value_krw - 100000000) / 100000000.0 * 100 AS total_return,
                  (SELECT COUNT(*) FROM simulated_trades t
                   WHERE t.agent_id = p.agent_id AND t.status != 'closed') AS open_positions
           FROM portfolio_snapshots p
           WHERE p.snapshot_date = (SELECT MAX(snapshot_date) FROM portfolio_snapshots)
           ORDER BY total_return DESC"""
    )
    api_cost = await fetchone(
        """SELECT SUM(estimated_cost) as total_cost, COUNT(*) as call_count
           FROM api_usage
           WHERE created_at >= DATE_TRUNC('month', NOW())"""
    )
    return {
        "snapshot": dict(today_snap) if today_snap else {},
        "agents": [dict(a) for a in agents_perf],
        "api_cost": dict(api_cost) if api_cost else {},
    }


@router.get("/portfolio")
async def get_unified_portfolio():
    """7개 에이전트 통합 포트폴리오 뷰"""
    rows = await fetchall(
        """SELECT t.ticker, c.name, t.market, c.sector,
                  COUNT(DISTINCT t.agent_id) AS agent_count,
                  STRING_AGG(DISTINCT t.agent_id, ',') AS agents,
                  AVG(t.price) AS avg_price
           FROM simulated_trades t
           LEFT JOIN company_info c ON t.ticker = c.ticker AND t.market = c.market
           WHERE t.status != 'closed'
           GROUP BY t.ticker, c.name, t.market, c.sector
           ORDER BY agent_count DESC"""
    )
    return [dict(r) for r in rows]


@router.get("/conflicts")
async def get_conflicts():
    """충돌·동의 종목"""
    debates = await fetchall(
        """SELECT * FROM investment_logs
           WHERE log_type = 'debate'
           ORDER BY created_at DESC LIMIT 20"""
    )
    return [dict(r) for r in debates]
