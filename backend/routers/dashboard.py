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
                  p.total_value_krw AS total_return,
                  p.daily_return,
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
    """5개 에이전트 통합 포트폴리오 뷰"""
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


@router.get("/consensus")
async def get_consensus():
    """중복 추천 종목 — 2개 이상 에이전트가 보유 중인 종목 + 각 에이전트별 이유(thesis)"""
    rows = await fetchall(
        """SELECT t.ticker, c.name, t.market, c.sector,
                  COUNT(DISTINCT t.agent_id) AS agent_count,
                  ARRAY_AGG(DISTINCT t.agent_id ORDER BY t.agent_id) AS agents,
                  JSON_AGG(
                      JSON_BUILD_OBJECT(
                          'agent_id', t.agent_id,
                          'thesis', l.thesis,
                          'status', t.status,
                          'price', t.price,
                          'trade_date', t.trade_date
                      ) ORDER BY t.agent_id
                  ) AS agent_details
           FROM simulated_trades t
           LEFT JOIN company_info c ON t.ticker = c.ticker AND t.market = c.market
           LEFT JOIN investment_logs l ON t.log_id = l.id
           WHERE t.status != 'closed'
           GROUP BY t.ticker, c.name, t.market, c.sector
           HAVING COUNT(DISTINCT t.agent_id) >= 2
           ORDER BY agent_count DESC"""
    )
    result = []
    for r in rows:
        row = dict(r)
        # agent_details가 문자열이면 파싱
        details = row.get("agent_details")
        if isinstance(details, str):
            import json
            details = json.loads(details)
        # thesis가 같은지 다른지 판단
        theses = [d.get("thesis") for d in (details or []) if d.get("thesis")]
        same_reason = len(set(theses)) <= 1 if theses else None
        result.append({
            "ticker": row["ticker"],
            "name": row["name"],
            "market": row["market"],
            "sector": row["sector"],
            "agent_count": row["agent_count"],
            "agents": row["agents"],
            "agent_details": details,
            "same_reason": same_reason,
        })
    return result


@router.get("/sector-concentration")
async def get_sector_concentration():
    """섹터 집중도 60%+ 경고 — event_logs 최신 건"""
    rows = await fetchall(
        """SELECT description, triggered_agents, created_at
           FROM event_logs
           WHERE event_type = 'sector_concentration'
           ORDER BY created_at DESC LIMIT 10"""
    )
    return [dict(r) for r in rows]


@router.get("/notifications")
async def get_notifications():
    """알림 — event_logs 최근 20건"""
    rows = await fetchall(
        """SELECT id, event_type, description, triggered_agents, created_at
           FROM event_logs
           ORDER BY created_at DESC LIMIT 20"""
    )
    return [dict(r) for r in rows]


@router.get("/sectors")
async def get_sectors():
    """섹터 ETF 수익률 — 최근 거래일 기준"""
    rows = await fetchall(
        """SELECT market, etf_ticker, etf_name,
                  return_1d, return_5d, return_20d, record_date
           FROM sector_etf_history
           WHERE record_date = (SELECT MAX(record_date) FROM sector_etf_history)
           ORDER BY market, return_1d DESC"""
    )
    return [dict(r) for r in rows]
