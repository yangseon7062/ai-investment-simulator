"""
온디맨드 종목 분석 API
- 사용자가 종목 + 에이전트 선택 → 즉석 분석 리포트
- investment_logs에 log_type='ondemand'로 저장
"""

import asyncio
from datetime import date
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.agents.definitions import get_agent, get_all_agents
from backend.agents.runner import (
    _build_agent_context, _build_agent_extra,
    _preprocess_candidates,
)
from backend.database import get_db, execute as db_execute
from backend.services.claude_service import generate_agent_decision
from backend.services.data_fetcher import (
    get_kr_prices, get_us_prices, get_exchange_rate,
)
from backend.services.news_fetcher import fetch_naver_stock_news, get_news_trend
from backend.services.data_fetcher import get_yfinance_news, get_foreign_buying, get_52week_high_low

router = APIRouter(prefix="/api/analyze", tags=["analyze"])


class AnalyzeRequest(BaseModel):
    ticker: str
    market: str          # "KR" or "US"
    agents: list[str]    # ["surfer", "strategist", ...] 또는 빈 리스트 → 전체


async def _fetch_candidate(ticker: str, market: str) -> dict:
    """단일 종목 데이터 수집 (가격 + 재무 + 뉴스 + 수급 + 52주 고저)"""
    # 1. 현재가
    if market == "KR":
        prices = await get_kr_prices([ticker])
    else:
        prices = await get_us_prices([ticker])

    price_data = prices.get(ticker, {})
    price = price_data.get("price", 0)

    # 종목 기본 정보 (company_info)
    async with get_db() as conn:
        info_row = await conn.fetchrow(
            "SELECT name, sector FROM company_info WHERE ticker = $1 AND market = $2",
            ticker, market,
        )
    name = info_row["name"] if info_row else ticker
    sector = info_row["sector"] if info_row else None

    candidate = {
        "ticker": ticker,
        "name": name,
        "market": market,
        "sector": sector,
        "price": price,
        "agent_score": 70,
    }

    # 2. 재무 데이터 (financials_cache)
    async with get_db() as conn:
        fin_rows = await conn.fetch(
            """SELECT fiscal_quarter, pbr, per, roic, revenue_growth,
                      gross_margin, fcf, debt_ratio
               FROM financials_cache
               WHERE ticker = $1 AND market = $2
               ORDER BY fiscal_quarter DESC LIMIT 8""",
            ticker, market,
        )
        sector_val_row = await conn.fetchrow(
            """SELECT median_per, median_pbr FROM sector_valuations
               WHERE market = $1 AND sector = $2
               AND calc_date = (SELECT MAX(calc_date) FROM sector_valuations)""",
            market, sector or "",
        ) if sector else None

    fin_list = [dict(r) for r in fin_rows]
    if fin_list:
        latest = fin_list[0]
        candidate.update({
            "pbr": latest["pbr"],
            "per": latest["per"],
            "roic": latest["roic"],
            "revenue_growth": latest["revenue_growth"],
            "gross_margin": latest["gross_margin"],
            "fcf": latest["fcf"],
            "debt_ratio": latest["debt_ratio"],
            "has_pbr_history": len(fin_list) >= 4,
            "has_roic_trend": sum(1 for r in fin_list if r["roic"] is not None) >= 4,
            "data_quarters": len(fin_list),
        })
        if len(fin_list) >= 2:
            candidate["financials_history"] = [
                {
                    "quarter": r["fiscal_quarter"],
                    "roic": r["roic"],
                    "pbr": r["pbr"],
                    "per": r["per"],
                    "revenue_growth": r["revenue_growth"],
                    "gross_margin": r["gross_margin"],
                }
                for r in fin_list[:8]
            ]
    else:
        candidate.update({"has_pbr_history": False, "has_roic_trend": False, "data_quarters": 0})

    if sector_val_row:
        candidate["has_sector_per"] = True
        candidate["sector_median_per"] = sector_val_row["median_per"]
        candidate["sector_median_pbr"] = sector_val_row["median_pbr"]
    else:
        candidate["has_sector_per"] = False

    # PBR 밴드 (전략가용 — 나중에 에이전트별로 활용)
    pbr_values = [r["pbr"] for r in fin_list if r.get("pbr") is not None]
    if len(pbr_values) >= 4:
        sorted_pbrs = sorted(pbr_values)
        pbr_min = sorted_pbrs[0]
        pbr_max = sorted_pbrs[-1]
        pbr_median = sorted_pbrs[len(sorted_pbrs) // 2]
        current_pbr = candidate.get("pbr")
        pbr_percentile = None
        if current_pbr is not None and pbr_max > pbr_min:
            pbr_percentile = round((current_pbr - pbr_min) / (pbr_max - pbr_min) * 100, 1)
        candidate["pbr_band_available"] = True
        candidate["pbr_band"] = {
            "min": round(pbr_min, 2), "max": round(pbr_max, 2),
            "median": round(pbr_median, 2), "current": current_pbr,
            "percentile": pbr_percentile, "quarters": len(pbr_values),
        }
        candidate["pbr_band_caution"] = False
    else:
        candidate["pbr_band_available"] = False
        candidate["pbr_band"] = None
        candidate["pbr_band_caution"] = False

    # 3. 뉴스
    try:
        if market == "KR":
            news = await fetch_naver_stock_news(ticker, name)
            candidate["recent_news"] = [n["title"] for n in news[:3]]
        else:
            news_map = await get_yfinance_news([ticker])
            candidate["recent_news"] = [n["title"] for n in news_map.get(ticker, [])[:3]]
    except Exception:
        pass

    # 4. 수급 (KR)
    if market == "KR":
        try:
            supply = await get_foreign_buying([ticker])
            if isinstance(supply, dict) and ticker in supply:
                candidate.update(supply[ticker])
        except Exception:
            pass

    # 5. 52주 고저
    try:
        hw = await get_52week_high_low([ticker], market)
        if isinstance(hw, dict) and ticker in hw:
            candidate.update(hw[ticker])
    except Exception:
        pass

    # 6. 뉴스 증가율 (미래탐색자용)
    try:
        trend = await get_news_trend(ticker, market)
        if trend.get("available"):
            candidate["news_trend"] = trend
    except Exception:
        pass

    return candidate


async def _get_market_context() -> dict:
    """최신 market_snapshots + FRED + VIX 등 컨텍스트 조회"""
    async with get_db() as conn:
        snap = await conn.fetchrow(
            "SELECT * FROM market_snapshots ORDER BY snapshot_date DESC LIMIT 1"
        )
    if not snap:
        return {"regime_kr": "횡보", "regime_us": "횡보"}

    ctx = dict(snap)
    # isoformat 변환
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in ctx.items()}


@router.post("/")
async def analyze_stock(req: AnalyzeRequest):
    ticker = req.ticker.strip().upper()
    market = req.market.strip().upper()
    if market not in ("KR", "US"):
        raise HTTPException(status_code=400, detail="market은 KR 또는 US")

    # 에이전트 목록 결정 (빈 리스트 → 전체 5개)
    all_agents = get_all_agents()
    if req.agents:
        selected = [get_agent(a) for a in req.agents if get_agent(a) is not None]
    else:
        selected = all_agents

    if not selected:
        raise HTTPException(status_code=400, detail="유효한 에이전트 없음")

    # 종목 데이터 수집
    try:
        candidate = await _fetch_candidate(ticker, market)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"종목 데이터 수집 실패: {e}")

    if not candidate.get("price") or candidate["price"] <= 0:
        raise HTTPException(status_code=404, detail=f"{ticker} 가격 조회 실패. 종목 코드/시장을 확인하세요.")

    # 시장 컨텍스트
    market_context = await _get_market_context()

    # 환율
    try:
        exchange_rate = await get_exchange_rate()
    except Exception:
        exchange_rate = None

    # 섹터 ETF
    async with get_db() as conn:
        etf_rows = await conn.fetch(
            """SELECT etf_name, etf_ticker, market, return_1d, return_5d
               FROM sector_etf_history
               WHERE record_date = (SELECT MAX(record_date) FROM sector_etf_history)
               ORDER BY market, return_1d DESC"""
        )
    sector_etf_data = [dict(r) for r in etf_rows]

    # 에이전트별 순차 분석 (TPM 대응 — 에이전트 간 10초 대기)
    results = {}
    for i, agent_config in enumerate(selected):
        if i > 0:
            await asyncio.sleep(10)

        agent_id = agent_config.agent_id

        # 후보 전처리 (에이전트별 required_data 필터 적용)
        candidates = _preprocess_candidates([dict(candidate)], agent_config)
        if not candidates:
            results[agent_id] = {
                "decision": "pass",
                "report_md": f"## [{agent_config.name_kr}] 분석 불가\n\n이 에이전트의 필수 데이터({', '.join(agent_config.required_data)})가 없어 분석할 수 없습니다.",
                "confidence": "low",
            }
            continue

        # 에이전트별 컨텍스트 필터링
        filtered_context = _build_agent_context(agent_config, market_context)
        filtered_extra = _build_agent_extra(agent_config, {
            "sector_etf": sector_etf_data,
            "exchange_rate": exchange_rate,
        })

        # 최근 30일 로그 (에이전트 메모리)
        async with get_db() as conn:
            log_rows = await conn.fetch(
                """SELECT log_type, tickers, thesis, created_at
                   FROM investment_logs
                   WHERE agent_id = $1 AND created_at > NOW() - INTERVAL '30 days'
                   ORDER BY created_at DESC LIMIT 10""",
                agent_id,
            )
        recent_logs = [
            {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}
            for r in log_rows
        ]

        try:
            decision = await generate_agent_decision(
                agent_config,
                filtered_context,
                candidates,
                [],           # 보유 포지션 없음 (온디맨드)
                recent_logs,
                None,         # 손절 내역 없음
                extra_context=filtered_extra,
                consensus_map={},
            )
        except Exception as e:
            decision = {
                "decision": "pass",
                "report_md": f"## [{agent_config.name_kr}] 분석 오류\n\n{e}",
                "confidence": "low",
            }

        results[agent_id] = decision

        # investment_logs 저장
        await db_execute(
            """INSERT INTO investment_logs
               (agent_id, log_type, tickers, report_md, confidence,
                market_regime_kr, market_regime_us)
               VALUES ($1, 'ondemand', $2, $3, $4, $5, $6)""",
            (
                agent_id, ticker,
                decision.get("report_md", ""),
                decision.get("confidence"),
                market_context.get("regime_kr"),
                market_context.get("regime_us"),
            ),
        )

        print(f"  [온디맨드] {agent_id} → {ticker} {decision.get('decision', 'pass')}")

    return {
        "ticker": ticker,
        "market": market,
        "name": candidate.get("name", ticker),
        "price": candidate["price"],
        "results": results,
    }
