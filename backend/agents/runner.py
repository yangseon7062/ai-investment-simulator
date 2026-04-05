"""
에이전트 병렬 실행 오케스트레이터 (16:00 KST)
1. 5개 에이전트 순차 실행
2. 충돌 감지 → 토론 리포트
3. portfolio_snapshots 기록
4. 오늘의 한 줄 요약 생성
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
from backend.services.claude_service import monitor_position, generate_postmortem


async def run_single_agent(agent_config, market_context: dict) -> dict:
    """단일 에이전트 실행 (매도 판단 → 신규 매수 판단)"""
    agent_id = agent_config.agent_id
    print(f"  [{agent_id}] 시작")

    # 1. 보유 포지션 테제 체크 → 매도 판단
    # monitor_daily=False인 에이전트(전략가)는 금요일에만 모니터링
    today_weekday = datetime.now().weekday()  # 0=월 ~ 4=금
    if agent_config.monitor_daily or today_weekday == 4:
        await _monitor_and_sell(agent_id, agent_config, market_context)

    # 2. 매도 후 보유 포지션 재조회 (PnL + thesis 포함)
    today_date = date.today()
    async with get_db() as conn:
        rows = await conn.fetch(
            """SELECT t.*, c.name, c.sector, l.thesis,
                      CASE WHEN t.price > 0 AND s.market_cap IS NOT NULL AND s.market_cap > 0
                           THEN ROUND(CAST((s.market_cap - t.price) / t.price * 100 AS NUMERIC), 2)
                           ELSE NULL END AS pnl_pct,
                      s.market_cap AS current_price
               FROM simulated_trades t
               LEFT JOIN company_info c ON t.ticker = c.ticker AND t.market = c.market
               LEFT JOIN investment_logs l ON t.log_id = l.id
               LEFT JOIN stock_scores s ON t.ticker = s.ticker AND s.market = t.market AND s.score_date = $2
               WHERE t.agent_id = $1 AND t.status != 'closed'""",
            agent_id, today_date,
        )
        positions = [
            {k: (v.isoformat() if hasattr(v, 'isoformat') else v) for k, v in dict(r).items()}
            for r in rows
        ]

    # 섹터 집중도 계산 (보유 포지션 기준)
    sector_count: dict[str, int] = {}
    for p in positions:
        sec = p.get("sector") or "기타"
        sector_count[sec] = sector_count.get(sec, 0) + 1
    total_pos = len(positions) or 1
    sector_concentration = {k: round(v / total_pos * 100) for k, v in sector_count.items()}

    # 타 에이전트 공감대 (보유 수 + 평균 수익률)
    async with get_db() as conn:
        consensus_rows = await conn.fetch(
            """SELECT t.ticker,
                      COUNT(DISTINCT t.agent_id) as agent_count,
                      ARRAY_AGG(DISTINCT t.agent_id) as agents,
                      AVG(
                          CASE WHEN t.price > 0 AND s.market_cap > 0
                               THEN (s.market_cap - t.price) / t.price * 100
                               ELSE NULL END
                      ) as avg_pnl_pct
               FROM simulated_trades t
               LEFT JOIN stock_scores s ON t.ticker = s.ticker AND s.market = t.market
                   AND s.score_date = (SELECT MAX(score_date) FROM stock_scores)
               WHERE t.status != 'closed' AND t.agent_id != $1
               GROUP BY t.ticker""",
            agent_id,
        )
        consensus_map = {
            r["ticker"]: {
                "agent_count": r["agent_count"],
                "agents": list(r["agents"]),
                "avg_pnl_pct": round(float(r["avg_pnl_pct"]), 1) if r["avg_pnl_pct"] is not None else None,
            }
            for r in consensus_rows
        }

    # 환율
    from backend.services.data_fetcher import get_exchange_rate as _get_rate
    try:
        current_exchange_rate = await _get_rate()
    except Exception:
        current_exchange_rate = None

    # 에이전트 MDD 계산 (portfolio_snapshots 전체 조회)
    async with get_db() as conn:
        snap_rows = await conn.fetch(
            "SELECT total_value_krw FROM portfolio_snapshots WHERE agent_id = $1 ORDER BY snapshot_date ASC",
            agent_id,
        )
    snap_values = [float(r["total_value_krw"] or 0) for r in snap_rows]
    if snap_values:
        peak = snap_values[0]
        mdd = 0.0
        for v in snap_values:
            if v > peak:
                peak = v
            dd = v - peak
            if dd < mdd:
                mdd = dd
        current_drawdown = snap_values[-1] - max(snap_values)
        agent_mdd = {"mdd": round(mdd, 2), "current_drawdown": round(current_drawdown, 2), "peak": round(max(snap_values), 2)}
    else:
        agent_mdd = {"mdd": 0.0, "current_drawdown": 0.0, "peak": 0.0}

    # 섹터 ETF 수익률 (최근 1일, sector_etf_history에서)
    async with get_db() as conn:
        etf_rows = await conn.fetch(
            """SELECT etf_name, etf_ticker, market, return_1d, return_5d
               FROM sector_etf_history
               WHERE record_date = (SELECT MAX(record_date) FROM sector_etf_history)
               ORDER BY market, return_1d DESC""",
        )
        sector_etf_data = [dict(r) for r in etf_rows]

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
        recent_logs = [{k: (v.isoformat() if hasattr(v, 'isoformat') else v) for k, v in dict(r).items()} for r in rows]

    # 최근 30일 손절 내역 (재진입 경계 정보)
    async with get_db() as conn:
        loss_rows = await conn.fetch(
            """SELECT ticker, pnl_pct, pnl_pct_krw, created_at
               FROM postmortems
               WHERE agent_id = $1 AND pnl_pct < 0 AND created_at > NOW() - INTERVAL '30 days'
               ORDER BY created_at DESC LIMIT 5""",
            agent_id,
        )
        recent_losses = [
            {k: (v.isoformat() if hasattr(v, 'isoformat') else v) for k, v in dict(r).items()}
            for r in loss_rows
        ]

    # 스코어 상위 종목 (KR + US)
    kr_candidates, us_candidates = await asyncio.gather(
        get_top_stocks(agent_id, "KR", top_n=20),
        get_top_stocks(agent_id, "US", top_n=20),
    )
    candidates = kr_candidates + us_candidates

    # 매크로는 섹터 ETF만 (개별 종목 매수 금지)
    if agent_config.etf_only:
        etf_tickers = {
            "TIGER 반도체": "091160", "TIGER 2차전지테마": "305720",
            "TIGER 헬스케어": "143850", "KODEX 방산": "475050",
            "TIGER 은행": "091170", "KODEX IT": "266360",
            "XLK": "XLK", "SMH": "SMH", "XLV": "XLV",
            "XLF": "XLF", "XLE": "XLE", "ITA": "ITA", "XLC": "XLC",
        }
        etf_candidates = [
            {"ticker": v, "name": k,
             "market": "US" if len(v) <= 4 and v.isalpha() else "KR",
             "agent_score": 70}
            for k, v in etf_tickers.items()
        ]
        # 실제 ETF 가격 수집
        from backend.services.data_fetcher import get_kr_prices, get_us_prices
        etf_kr = [c["ticker"] for c in etf_candidates if c["market"] == "KR"]
        etf_us = [c["ticker"] for c in etf_candidates if c["market"] == "US"]
        etf_prices_kr, etf_prices_us = await asyncio.gather(
            get_kr_prices(etf_kr) if etf_kr else asyncio.sleep(0),
            get_us_prices(etf_us) if etf_us else asyncio.sleep(0),
        )
        etf_price_map = {}
        if isinstance(etf_prices_kr, dict):
            etf_price_map.update({t: v["price"] for t, v in etf_prices_kr.items() if v.get("price")})
        if isinstance(etf_prices_us, dict):
            etf_price_map.update({t: v["price"] for t, v in etf_prices_us.items() if v.get("price")})
        for c in etf_candidates:
            c["price"] = etf_price_map.get(c["ticker"], 0)
        # 가격 없는 ETF 제외
        candidates = [c for c in etf_candidates if c.get("price", 0) > 0]

    # 베어는 인버스 ETF만
    elif agent_config.inverse_etf_only:
        from backend.config import INVERSE_ETFS
        from backend.services.data_fetcher import get_kr_prices, get_us_prices
        inv_candidates = [
            {"ticker": v, "name": k, "market": "KR" if k.startswith("KR") else "US", "agent_score": 80}
            for k, v in INVERSE_ETFS.items()
        ]
        inv_kr = [c["ticker"] for c in inv_candidates if c["market"] == "KR"]
        inv_us = [c["ticker"] for c in inv_candidates if c["market"] == "US"]
        inv_prices_kr, inv_prices_us = await asyncio.gather(
            get_kr_prices(inv_kr) if inv_kr else asyncio.sleep(0),
            get_us_prices(inv_us) if inv_us else asyncio.sleep(0),
        )
        inv_price_map = {}
        if isinstance(inv_prices_kr, dict):
            inv_price_map.update({t: v["price"] for t, v in inv_prices_kr.items() if v.get("price")})
        if isinstance(inv_prices_us, dict):
            inv_price_map.update({t: v["price"] for t, v in inv_prices_us.items() if v.get("price")})
        for c in inv_candidates:
            c["price"] = inv_price_map.get(c["ticker"], 0)
        candidates = [c for c in inv_candidates if c.get("price", 0) > 0]
    else:
        candidates = candidates[:20]
        # 거래량 급등 종목 강제 포함 (technical_score >= 80, 기존 후보에 없는 종목)
        held_tickers = {p["ticker"] for p in positions}
        existing_tickers = {c["ticker"] for c in candidates}
        today_date = date.today()
        async with get_db() as conn:
            spike_rows = await conn.fetch(
                """SELECT s.ticker, s.market, s.technical_score, s.fundamental_score, s.market_cap,
                          c.name, c.sector
                   FROM stock_scores s
                   LEFT JOIN company_info c ON s.ticker = c.ticker AND s.market = c.market
                   WHERE s.score_date = $1 AND s.technical_score >= 80
                   ORDER BY s.technical_score DESC LIMIT 10""",
                today_date,
            )
        for row in spike_rows:
            t = row["ticker"]
            if t not in existing_tickers and t not in held_tickers:
                candidates.append({
                    "ticker": t,
                    "name": row["name"],
                    "sector": row["sector"],
                    "market": row["market"],
                    "technical_score": row["technical_score"],
                    "fundamental_score": row["fundamental_score"],
                    "agent_score": row["technical_score"],
                    "price": row["market_cap"],
                    "volume_spike": True,  # LLM이 이유를 알 수 있도록 표시
                })

    # 후보 종목 추가 정보 수집 (뉴스 + 수급 + 52주 고저)
    # volume_spike 종목 포함하여 전체 후보에서 뉴스 수집 (top5 제한 제거)
    from backend.services.news_fetcher import fetch_naver_stock_news
    from backend.services.data_fetcher import get_yfinance_news, get_foreign_buying, get_52week_high_low

    kr_all = [(c["ticker"], c.get("name", c["ticker"])) for c in candidates if c.get("market") == "KR"]
    us_all = [c["ticker"] for c in candidates if c.get("market") == "US"]
    kr_tickers_top = [t for t, _ in kr_all]

    (kr_news_results, us_news_map, kr_supply, kr_52w, us_52w) = await asyncio.gather(
        asyncio.gather(*[fetch_naver_stock_news(t, n) for t, n in kr_all], return_exceptions=True) if kr_all else asyncio.sleep(0),
        get_yfinance_news(us_all) if us_all else asyncio.sleep(0),
        get_foreign_buying(kr_tickers_top) if kr_tickers_top else asyncio.sleep(0),
        get_52week_high_low(kr_tickers_top, "KR") if kr_tickers_top else asyncio.sleep(0),
        get_52week_high_low(us_all, "US") if us_all else asyncio.sleep(0),
    )

    # 뉴스
    if kr_all and isinstance(kr_news_results, (list, tuple)):
        kr_news_map = {t: (r if isinstance(r, list) else []) for (t, _), r in zip(kr_all, kr_news_results)}
        for c in candidates:
            if c.get("market") == "KR" and c["ticker"] in kr_news_map:
                c["recent_news"] = [n["title"] for n in kr_news_map[c["ticker"]][:3]]
    if isinstance(us_news_map, dict):
        for c in candidates:
            if c.get("market") == "US" and c["ticker"] in us_news_map:
                c["recent_news"] = [n["title"] for n in us_news_map[c["ticker"]][:3]]

    # 수급 (KR)
    if isinstance(kr_supply, dict):
        for c in candidates:
            if c.get("market") == "KR" and c["ticker"] in kr_supply:
                c.update(kr_supply[c["ticker"]])

    # 52주 고저
    for hw, mkt in [(kr_52w, "KR"), (us_52w, "US")]:
        if isinstance(hw, dict):
            for c in candidates:
                if c.get("market") == mkt and c["ticker"] in hw:
                    c.update(hw[c["ticker"]])

    # PBR/PER/ROIC/revenue_growth (financials_cache 배치 쿼리)
    ticker_market_pairs = [(c["ticker"], c.get("market", "KR")) for c in candidates]
    if ticker_market_pairs:
        tickers_only = [t for t, _ in ticker_market_pairs]
        async with get_db() as conn:
            fin_rows = await conn.fetch(
                """SELECT DISTINCT ON (ticker, market)
                          ticker, market, pbr, per, roic, revenue_growth,
                          gross_margin, fcf, debt_ratio
                   FROM financials_cache
                   WHERE ticker = ANY($1)
                   ORDER BY ticker, market, fiscal_quarter DESC""",
                tickers_only,
            )
        fin_map = {(r["ticker"], r["market"]): dict(r) for r in fin_rows}
        for c in candidates:
            key = (c["ticker"], c.get("market", "KR"))
            if key in fin_map:
                row = fin_map[key]
                c["pbr"] = row["pbr"]
                c["per"] = row["per"]
                c["roic"] = row["roic"]
                c["revenue_growth"] = row["revenue_growth"]
                c["gross_margin"] = row["gross_margin"]
                c["fcf"] = row["fcf"]
                c["debt_ratio"] = row["debt_ratio"]

    # 후보 종목에 공감대 정보 추가 (보유 현황만 — 판단 의도 제외)
    for c in candidates:
        t = c["ticker"]
        if t in consensus_map:
            c["other_agents_holding"] = consensus_map[t]

    # 후보 전처리: null 정규화 + required_data 필터 + price 없는 종목 제거
    candidates = _preprocess_candidates(candidates, agent_config)

    if not candidates:
        await _save_pass_log(agent_id, "유효한 후보 종목 없음 (데이터 부족)", market_context)
        return {"agent_id": agent_id, "decision": "pass", "reason": "후보 없음"}

    # 에이전트별 컨텍스트 필터링 (독립성 강화)
    filtered_context = _build_agent_context(agent_config, market_context)
    filtered_extra = _build_agent_extra(agent_config, {
        "sector_concentration": sector_concentration,
        "sector_etf": sector_etf_data,
        "exchange_rate": current_exchange_rate,
        "mdd": agent_mdd,
    })
    filtered_consensus = consensus_map if agent_config.show_consensus else {}

    # Claude 투자 판단
    decision = await generate_agent_decision(
        agent_config,
        filtered_context,
        candidates,
        positions,
        recent_logs,
        recent_losses,
        extra_context=filtered_extra,
        consensus_map=filtered_consensus,
    )

    # LLM 응답 검증: 환각 종목 차단 + 가격 보정
    decision = _validate_decision(decision, candidates)

    # 결과 처리
    decision_type = decision.get("decision")
    if decision_type == "buy" and decision.get("ticker"):
        await _execute_buy(agent_id, agent_config, decision)
    elif decision_type == "hold":
        # hold: 관심 있으나 진입 조건 미충족 — 로그 타입 구분
        await _save_hold_log(agent_id, decision, market_context)
    else:
        # pass: 전략 기준 대상 없음
        await _save_pass_log(agent_id, decision.get("pass_reason", "전략 기준 대상 없음"), market_context, decision.get("report_md"))

    print(f"  [{agent_id}] 완료 → {decision.get('decision')} {decision.get('ticker', '')}")
    return {"agent_id": agent_id, **decision}


def _build_agent_context(agent_config, market_context: dict) -> dict:
    """에이전트 독립성 강화: 전략과 무관한 거시 컨텍스트 차단"""
    ctx = dict(market_context)
    if not agent_config.show_macro_context:
        # 거시/섹터 정보 제거 (서퍼, 탐색자)
        ctx.pop("narrative_kr", None)
        ctx.pop("narrative_us", None)
        ctx.pop("fred", None)
        ctx.pop("fear_greed", None)
        ctx.pop("gold_drop", None)
        ctx.pop("equity_drop", None)
        ctx.pop("gold_change_pct", None)
        ctx.pop("spx_change_pct", None)
    return ctx


def _build_agent_extra(agent_config, extra: dict) -> dict:
    """에이전트별 extra_context 필터링"""
    filtered = dict(extra)
    if not agent_config.show_mdd:
        filtered.pop("mdd", None)
    if not agent_config.show_macro_context:
        filtered.pop("sector_etf", None)
    return filtered


def _preprocess_candidates(candidates: list[dict], agent_config) -> list[dict]:
    """
    후보 종목 전처리:
    1. required_data 없는 종목 제외 (가격 없음 등)
    2. null → "⚠️없음" 변환 + data_gaps 표시
    3. price=0 또는 None 제외
    """
    NUMERIC_FIELDS = ["pbr", "per", "roic", "revenue_growth",
                      "foreign_net_3d", "institution_net_3d",
                      "high_52w", "low_52w", "pct_from_high", "pct_from_low"]
    required = set(agent_config.required_data)
    result = []

    for c in candidates:
        # 가격 없는 종목은 모든 에이전트에서 제외
        price = c.get("price")
        if not price or price <= 0:
            continue

        # required_data 검증 — 없거나 null이면 제외
        skip = False
        for req in required:
            if req == "price":
                continue  # 위에서 이미 처리
            val = c.get(req)
            if val is None or val == "⚠️없음":
                skip = True
                break
        if skip:
            continue

        # null → "⚠️없음" 변환 + data_gaps 수집
        gaps = []
        for field in NUMERIC_FIELDS:
            if c.get(field) is None:
                c[field] = "⚠️없음"
                gaps.append(field)

        if not c.get("recent_news"):
            gaps.append("recent_news")

        if gaps:
            c["data_gaps"] = gaps

        result.append(c)

    return result


def _validate_decision(decision: dict, candidates: list[dict]) -> dict:
    """
    LLM 응답 검증:
    1. 후보 목록에 없는 종목(환각) → pass 처리
    2. 가격이 실제가 대비 ±10% 초과 시 실제가로 강제 교체
    3. decision=buy인데 ticker/price 없으면 pass
    """
    if decision.get("decision") != "buy":
        return decision

    ticker = decision.get("ticker")
    if not ticker:
        return {**decision, "decision": "pass", "pass_reason": "ticker 누락"}

    candidate_map = {c["ticker"]: c for c in candidates}

    # 환각 종목 차단
    if ticker not in candidate_map:
        print(f"  [검증] 환각 종목 감지: {ticker} → pass 처리")
        return {**decision, "decision": "pass", "pass_reason": f"환각 종목 감지: {ticker}"}

    # 가격 보정
    real_price = candidate_map[ticker].get("price", 0)
    llm_price = decision.get("price", 0)
    if real_price and real_price > 0:
        if llm_price and llm_price > 0:
            diff_pct = abs(llm_price - real_price) / real_price
            if diff_pct > 0.1:
                print(f"  [검증] {ticker} 가격 보정: LLM={llm_price:,.0f} → 실제={real_price:,.0f}")
                decision = {**decision, "price": real_price, "price_corrected": True}
        else:
            decision = {**decision, "price": real_price}

    return decision


async def _check_entry_condition(agent_config, market_context: dict) -> bool:
    """베어 진입 조건 체크 (하락장/변동성 급등 시에만 진입)"""
    if agent_config.agent_id == "bear":
        regime_kr = market_context.get("regime_kr", "횡보")
        regime_us = market_context.get("regime_us", "횡보")
        return "하락" in regime_kr or "하락" in regime_us or "변동성" in regime_kr or "변동성" in regime_us

    return True


async def _execute_buy(agent_id: str, agent_config, decision: dict):
    """매수 실행 (수익률 추적 방식 - 현금 차감 없음)"""
    ticker = decision["ticker"]
    market = decision.get("market", "KR")
    price = decision.get("price", 0)
    thesis = decision.get("thesis", "")
    report_md = decision.get("report_md", "")
    entry_advice = decision.get("entry_advice", "")

    # 분할매수 조언을 리포트에 추가
    if entry_advice:
        report_md += f"\n\n**매수 조언**: {entry_advice}"

    if price <= 0:
        return

    exchange_rate = 1.0
    if market == "US":
        exchange_rate = await get_exchange_rate()

    # 로그 저장 + log_id 획득
    async with get_db() as conn:
        log_id = await conn.fetchval(
            """INSERT INTO investment_logs
               (agent_id, log_type, tickers, report_md, thesis)
               VALUES ($1, 'buy', $2, $3, $4)
               RETURNING id""",
            agent_id, ticker, report_md, thesis,
        )

    # 매수 기록 (quantity=0, 현금 차감 없음)
    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO simulated_trades
               (agent_id, ticker, market, name, action, price, quantity,
                exchange_rate, log_id, highest_price, status)
               VALUES ($1, $2, $3, $4, 'BUY', $5, 0, $6, $7, $8, 'buy')""",
            agent_id, ticker, market,
            decision.get("name", ticker),
            price, exchange_rate,
            log_id, price,
        )


async def _monitor_and_sell(agent_id: str, agent_config, market_context: dict):
    """보유 포지션 테제 유효성 체크 → 매도 판단"""
    from backend.services.data_fetcher import get_kr_prices, get_us_prices

    async with get_db() as conn:
        rows = await conn.fetch(
            """SELECT t.*, l.report_md as buy_report, l.thesis
               FROM simulated_trades t
               LEFT JOIN investment_logs l ON t.log_id = l.id
               WHERE t.agent_id = $1 AND t.status != 'closed'""",
            agent_id,
        )
        positions = [dict(r) for r in rows]

    if not positions:
        return

    kr_tickers = [p["ticker"] for p in positions if p["market"] == "KR"]
    us_tickers = [p["ticker"] for p in positions if p["market"] == "US"]

    # 가격 + 뉴스 병렬 수집
    from backend.services.news_fetcher import fetch_naver_stock_news
    from backend.services.data_fetcher import get_yfinance_news

    kr_name_map = {p["ticker"]: (p.get("name") or p["ticker"]) for p in positions if p["market"] == "KR"}
    kr_pairs = [(t, kr_name_map[t]) for t in kr_tickers]

    prices_kr, prices_us, kr_monitor_news, us_monitor_news = await asyncio.gather(
        get_kr_prices(kr_tickers) if kr_tickers else asyncio.sleep(0),
        get_us_prices(us_tickers) if us_tickers else asyncio.sleep(0),
        asyncio.gather(*[fetch_naver_stock_news(t, n) for t, n in kr_pairs], return_exceptions=True) if kr_pairs else asyncio.sleep(0),
        get_yfinance_news(us_tickers) if us_tickers else asyncio.sleep(0),
    )

    prices = {}
    if isinstance(prices_kr, dict):
        prices.update(prices_kr)
    if isinstance(prices_us, dict):
        prices.update(prices_us)

    # 뉴스 매핑
    monitor_news_map: dict = {}
    if kr_pairs and isinstance(kr_monitor_news, (list, tuple)):
        for (t, _), news in zip(kr_pairs, kr_monitor_news):
            monitor_news_map[t] = [n["title"] for n in news[:3]] if isinstance(news, list) else []
    if isinstance(us_monitor_news, dict):
        for t, news in us_monitor_news.items():
            monitor_news_map[t] = [n["title"] for n in news[:3]] if isinstance(news, list) else []

    for pos in positions:
        ticker = pos["ticker"]
        price_data = prices.get(ticker)
        if not price_data:
            continue
        current_price = price_data["price"]

        # 최신 뉴스 포지션에 추가
        pos["recent_news"] = monitor_news_map.get(ticker, [])

        # 트레일링 스탑 (서퍼)
        if agent_config.trailing_stop_pct and pos.get("highest_price"):
            highest = pos["highest_price"]
            if (highest - current_price) / highest * 100 >= agent_config.trailing_stop_pct:
                await _execute_sell_position(pos, current_price, agent_config, "트레일링 스탑 발동", market_context)
                continue
            if current_price > highest:
                await db_execute(
                    "UPDATE simulated_trades SET highest_price = $1 WHERE id = $2",
                    (current_price, pos["id"]),
                )

        # 보유 기간 계산
        try:
            buy_date = datetime.fromisoformat(str(pos["trade_date"])[:10]).date()
            holding_days = (datetime.now().date() - buy_date).days
        except Exception:
            holding_days = 0

        # LLM 테제 유효성 체크
        result = await monitor_position(agent_config, pos, current_price, market_context, pos.get("thesis", ""), holding_days)
        new_status = result.get("status", "hold")

        await db_execute(
            """INSERT INTO investment_logs
               (agent_id, log_type, tickers, report_md, thesis_valid, market_regime_kr, market_regime_us)
               VALUES ($1, 'monitor', $2, $3, $4, $5, $6)""",
            (agent_id, ticker, result.get("report_md", ""), result.get("thesis_valid", True),
             market_context.get("regime_kr"), market_context.get("regime_us")),
        )

        if new_status == "sell":
            await _execute_sell_position(pos, current_price, agent_config, result.get("sell_reason", ""), market_context)
        elif new_status != pos.get("status"):
            await db_execute(
                "UPDATE simulated_trades SET status = $1 WHERE id = $2",
                (new_status, pos["id"]),
            )


async def _execute_sell_position(position: dict, current_price: float, agent_config, reason: str, market_context: dict):
    """매도 실행 + 사후 검증"""
    agent_id = position["agent_id"]
    ticker = position["ticker"]
    market = position["market"]

    exchange_rate = 1.0
    if market == "US":
        exchange_rate = await get_exchange_rate()

    sell_report = f"## 매도 판단\n\n**사유**: {reason}\n\n**매도가**: {current_price:,.0f}\n"

    await db_execute(
        """INSERT INTO investment_logs
           (agent_id, log_type, tickers, report_md, thesis_valid, market_regime_kr, market_regime_us)
           VALUES ($1, 'sell', $2, $3, false, $4, $5)""",
        (agent_id, ticker, sell_report,
         market_context.get("regime_kr"), market_context.get("regime_us")),
    )
    await db_execute(
        "UPDATE simulated_trades SET status = 'closed' WHERE id = $1",
        (position["id"],),
    )

    buy_price = position["price"]
    buy_exchange_rate = position.get("exchange_rate") or 1.0
    pnl_pct = (current_price - buy_price) / buy_price * 100
    pnl_pct_krw = pnl_pct
    if market == "US" and buy_exchange_rate > 0:
        pnl_pct_krw = (current_price * exchange_rate - buy_price * buy_exchange_rate) / (buy_price * buy_exchange_rate) * 100

    holding_days = (datetime.now().date() - datetime.fromisoformat(str(position["trade_date"])[:10]).date()).days
    postmortem_report = await generate_postmortem(
        agent_config, ticker, position.get("name", ticker),
        position.get("buy_report") or "", sell_report,
        pnl_pct, pnl_pct_krw, holding_days,
    )

    await db_execute(
        """INSERT INTO postmortems
           (agent_id, ticker, buy_log_id, pnl_pct, pnl_pct_krw, was_correct, report_md)
           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
        (agent_id, ticker, position.get("log_id"),
         pnl_pct, pnl_pct_krw, pnl_pct > 0, postmortem_report),
    )


async def _save_hold_log(agent_id: str, decision: dict, market_context: dict):
    """관망(hold) 로그 저장 — 관심 종목 있음, 진입 조건 미충족"""
    ticker = decision.get("ticker") or ""
    next_condition = decision.get("next_condition", "")
    risk_note = decision.get("risk_note", "")
    report_md = decision.get("report_md") or (
        f"## 관망 (조건 대기)\n\n"
        f"**관심 종목**: {ticker}\n"
        f"**다음 조건**: {next_condition}\n"
        f"**리스크**: {risk_note}"
    )
    await db_execute(
        """INSERT INTO investment_logs
           (agent_id, log_type, tickers, report_md, market_regime_kr, market_regime_us)
           VALUES ($1, 'hold', $2, $3, $4, $5)""",
        (
            agent_id, ticker or None, report_md,
            market_context.get("regime_kr"),
            market_context.get("regime_us"),
        ),
    )


async def _save_pass_log(agent_id: str, reason: str, market_context: dict, report_md: str = None):
    """패스(pass) 로그 저장 — 전략 기준 대상 종목 없음"""
    md = report_md or f"## 패스\n\n**사유**: {reason}"
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


async def save_portfolio_snapshots():
    """모든 에이전트 포트폴리오 일별 스냅샷 저장 (수익률 방식)
    total_value_krw = 평균 수익률 % (예: 2.5 → +2.5%)
    """
    today = date.today()

    for agent in get_all_agents():
        agent_id = agent.agent_id

        async with get_db() as conn:
            positions = [dict(r) for r in await conn.fetch(
                "SELECT ticker, price as buy_price FROM simulated_trades WHERE agent_id = $1 AND status != 'closed'",
                agent_id,
            )]

            pnl_list = []
            for pos in positions:
                score_row = await conn.fetchrow(
                    "SELECT market_cap FROM stock_scores WHERE ticker = $1 AND score_date = $2",
                    pos["ticker"], today,
                )
                current_price = score_row["market_cap"] if score_row else None
                if current_price and pos["buy_price"] and pos["buy_price"] > 0:
                    pnl_list.append((current_price - pos["buy_price"]) / pos["buy_price"] * 100)

            realized_avg = await conn.fetchval(
                "SELECT AVG(pnl_pct) FROM postmortems WHERE agent_id = $1", agent_id,
            ) or 0.0

        all_pnls = pnl_list + ([float(realized_avg)] if realized_avg else [])
        avg_return = round(sum(all_pnls) / len(all_pnls), 2) if all_pnls else 0.0

        async with get_db() as conn:
            prev_row = await conn.fetchrow(
                "SELECT total_value_krw FROM portfolio_snapshots WHERE agent_id = $1 ORDER BY snapshot_date DESC LIMIT 1",
                agent_id,
            )

        prev_return = float(prev_row["total_value_krw"]) if prev_row and prev_row["total_value_krw"] is not None else 0.0
        daily_return = round(avg_return - prev_return, 2)

        await db_execute(
            """INSERT INTO portfolio_snapshots
               (agent_id, snapshot_date, cash_krw, stock_value_krw, total_value_krw, daily_return)
               VALUES ($1, $2, 0, 0, $3, $4)
               ON CONFLICT (agent_id, snapshot_date) DO UPDATE SET
                 total_value_krw = EXCLUDED.total_value_krw,
                 daily_return = EXCLUDED.daily_return""",
            (agent_id, today, avg_return, daily_return),
        )


# ── 메인 실행 ──────────────────────────────────────────────────────

async def run_all_agents(price_spikes: dict | None = None):
    """16:00 KST 전체 에이전트 실행 (매도 → 매수)"""
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
        "date": today.isoformat(),
        "price_spikes": price_spikes or {},  # 급락 종목 {ticker: change_pct}
    }

    agents = get_all_agents()
    decisions = []
    for agent in agents:
        try:
            result = await run_single_agent(agent, market_context)
            decisions.append(result)
        except Exception as e:
            print(f"  [{agent.agent_id}] 오류: {e}")
        await asyncio.sleep(10)  # Groq TPM 한도 대응 (에이전트 간 10초 대기)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 후처리 시작")

    await detect_conflicts_and_debate(decisions)
    await save_portfolio_snapshots()

    from backend.pipeline.position_monitor import check_sector_concentration
    await check_sector_concentration()

    summary_input = [
        {"agent": d.get("agent_id"), "decision": d.get("decision"), "ticker": d.get("ticker"), "thesis": d.get("thesis")}
        for d in decisions
    ]
    daily_summary = await generate_daily_summary(summary_input)

    await db_execute(
        "UPDATE market_snapshots SET daily_summary = $1 WHERE snapshot_date = $2",
        (daily_summary, today),
    )

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 완료 - {daily_summary}")
    return decisions
