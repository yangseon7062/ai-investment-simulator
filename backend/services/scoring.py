"""
종목 스코어링 엔진 (07:00 KST 실행)
- 950개 종목 일별 사전 계산 → stock_scores 테이블 저장
- 기술적 / 재무 / 감성 스코어 → 복합 스코어
- 에이전트별 가중치는 에이전트 실행 시 적용
"""

import asyncio
import numpy as np
import pandas as pd
from datetime import datetime, date
from typing import Optional

from backend.database import get_db
from backend.services.data_fetcher import get_us_prices, get_kr_prices, get_foreign_buying, get_us_financials


# ── 기술적 지표 계산 ───────────────────────────────────────────────

def calc_rsi(prices: list[float], period: int = 14) -> Optional[float]:
    if len(prices) < period + 1:
        return None
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def calc_ma_signal(prices: list[float]) -> float:
    """
    이동평균 신호 스코어 (0~100)
    - 현재가 > MA20 > MA60: 강한 상승 (100)
    - 현재가 < MA20 < MA60: 강한 하락 (0)
    """
    if len(prices) < 60:
        return 50.0
    current = prices[-1]
    ma20 = np.mean(prices[-20:])
    ma60 = np.mean(prices[-60:])

    score = 50.0
    if current > ma20:
        score += 20
    if current > ma60:
        score += 15
    if ma20 > ma60:
        score += 15
    return min(100.0, max(0.0, score))


def calc_volume_signal(volumes: list[float]) -> float:
    """
    거래량 신호 스코어 (0~100)
    최근 거래량 vs 20일 평균
    """
    if len(volumes) < 20:
        return 50.0
    avg_vol = np.mean(volumes[-20:])
    if avg_vol == 0:
        return 50.0
    ratio = volumes[-1] / avg_vol
    # 2배 이상 = 100, 0.5배 이하 = 0
    score = min(100.0, max(0.0, (ratio - 0.5) / 1.5 * 100))
    return round(score, 2)


def calc_technical_score(prices: list[float], volumes: list[float]) -> float:
    """기술적 스코어 (0~100)"""
    rsi = calc_rsi(prices) or 50.0
    ma_signal = calc_ma_signal(prices)
    vol_signal = calc_volume_signal(volumes)

    # RSI: 중립(50) 기준 → 과매수(70+)는 단기 위험이므로 70~80 구간 감점
    rsi_score = rsi
    if rsi > 75:
        rsi_score = 75 - (rsi - 75) * 1.5   # 과열 패널티

    return round(rsi_score * 0.4 + ma_signal * 0.4 + vol_signal * 0.2, 2)


# ── 재무 스코어 ────────────────────────────────────────────────────

async def calc_fundamental_score(ticker: str, market: str) -> float:
    """financials_cache에서 재무 스코어 계산 (0~100)"""
    async with get_db() as conn:
        row = await conn.fetchrow(
            """SELECT roic, pbr, per, revenue_growth
               FROM financials_cache
               WHERE ticker = $1 AND market = $2
               ORDER BY fiscal_quarter DESC LIMIT 1""",
            ticker, market,
        )

    if not row:
        return 50.0

    score = 50.0
    roic = row["roic"]
    pbr = row["pbr"]
    per = row["per"]
    growth = row["revenue_growth"]

    # ROIC: 15% 이상이면 고득점
    if roic is not None:
        if roic >= 20:
            score += 20
        elif roic >= 15:
            score += 15
        elif roic >= 10:
            score += 8
        elif roic < 0:
            score -= 15

    # PBR: 낮을수록 저평가 (가치주 관점)
    if pbr is not None:
        if pbr < 1.0:
            score += 15
        elif pbr < 2.0:
            score += 8
        elif pbr > 5.0:
            score -= 10

    # PER: 적정 구간 선호
    if per is not None and per > 0:
        if per < 15:
            score += 10
        elif per < 25:
            score += 5
        elif per > 50:
            score -= 10

    # 매출 성장률
    if growth is not None:
        if growth >= 20:
            score += 15
        elif growth >= 10:
            score += 8
        elif growth < 0:
            score -= 10

    return round(min(100.0, max(0.0, score)), 2)


# ── 복합 스코어 ────────────────────────────────────────────────────

def calc_composite_score(
    technical: float,
    fundamental: float,
    weights: dict = None,
) -> float:
    """기술적 + 재무 스코어 가중 합산 (감성 스코어 미사용)"""
    if weights is None:
        weights = {"technical": 0.5, "fundamental": 0.5}
    total = weights.get("technical", 0.5) + weights.get("fundamental", 0.5)
    tw = weights.get("technical", 0.5) / total
    fw = weights.get("fundamental", 0.5) / total
    return round(technical * tw + fundamental * fw, 2)


# ── 스크리닝 풀 로드 ────────────────────────────────────────────────

async def load_screening_pool() -> tuple[list[str], list[str]]:
    """
    DB에서 스크리닝 대상 종목 로드
    KR: KOSPI200 + KOSDAQ150
    US: S&P500 + NASDAQ100
    """
    async with get_db() as conn:
        kr_rows = await conn.fetch("SELECT ticker FROM company_info WHERE market = 'KR'")
        us_rows = await conn.fetch("SELECT ticker FROM company_info WHERE market = 'US'")

    kr_tickers = [r["ticker"] for r in kr_rows]
    us_tickers = [r["ticker"] for r in us_rows]
    return kr_tickers, us_tickers


# ── 재무 캐시 업데이트 ─────────────────────────────────────────────

async def _update_financials_cache(us_tickers: list, kr_tickers: list):
    """캐시 없는 종목 재무 데이터 수집 (US: yfinance, KR: yfinance)"""
    from datetime import datetime
    quarter = f"{datetime.now().year}Q{(datetime.now().month - 1) // 3 + 1}"

    # 이미 캐시된 종목 제외
    async with get_db() as conn:
        cached = await conn.fetch(
            "SELECT ticker FROM financials_cache WHERE fiscal_quarter = $1", quarter
        )
    cached_set = {r["ticker"] for r in cached}

    to_fetch_us = [t for t in us_tickers if t not in cached_set]
    to_fetch_kr = [t for t in kr_tickers if t not in cached_set]

    # US 재무 수집 (병렬, 최대 20개)
    async def _save_us(ticker):
        try:
            data = await get_us_financials(ticker)
            if not data:
                return
            async with get_db() as conn:
                await conn.execute(
                    """INSERT INTO financials_cache
                       (ticker, market, fiscal_quarter, revenue, operating_income, net_income,
                        total_assets, invested_capital, roic, pbr, per, revenue_growth,
                        gross_margin, fcf, debt_ratio)
                       VALUES ($1,'US',$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                       ON CONFLICT (ticker, market, fiscal_quarter) DO UPDATE SET
                         roic=EXCLUDED.roic, pbr=EXCLUDED.pbr, per=EXCLUDED.per,
                         revenue_growth=EXCLUDED.revenue_growth,
                         gross_margin=EXCLUDED.gross_margin, fcf=EXCLUDED.fcf,
                         debt_ratio=EXCLUDED.debt_ratio, updated_at=NOW()""",
                    ticker, quarter, data.get("revenue"), data.get("operating_income"),
                    data.get("net_income"), data.get("total_assets"), data.get("invested_capital"),
                    data.get("roic"), data.get("pbr"), data.get("per"), data.get("revenue_growth"),
                    data.get("gross_margin"), data.get("fcf"), data.get("debt_ratio"),
                )
        except Exception:
            pass

    # KR 재무 수집 (yfinance, KOSPI 우선 → KOSDAQ 폴백)
    async def _save_kr(ticker):
        try:
            data = await get_us_financials(ticker + ".KS")
            if not data:
                data = await get_us_financials(ticker + ".KQ")  # KOSDAQ 폴백
            if not data:
                return
            async with get_db() as conn:
                await conn.execute(
                    """INSERT INTO financials_cache
                       (ticker, market, fiscal_quarter, revenue, operating_income, net_income,
                        total_assets, invested_capital, roic, pbr, per, revenue_growth)
                       VALUES ($1,'KR',$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                       ON CONFLICT (ticker, market, fiscal_quarter) DO UPDATE SET
                         roic=EXCLUDED.roic, pbr=EXCLUDED.pbr, per=EXCLUDED.per,
                         revenue_growth=EXCLUDED.revenue_growth, updated_at=NOW()""",
                    ticker, quarter, data.get("revenue"), data.get("operating_income"),
                    data.get("net_income"), data.get("total_assets"), data.get("invested_capital"),
                    data.get("roic"), data.get("pbr"), data.get("per"), data.get("revenue_growth"),
                )
        except Exception:
            pass

    tasks = [_save_us(t) for t in to_fetch_us[:20]] + [_save_kr(t) for t in to_fetch_kr[:10]]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
        print(f"  재무 캐시: US {len(to_fetch_us[:20])}개 + KR {len(to_fetch_kr[:10])}개 업데이트")


# ── 메인 스코어링 실행 ──────────────────────────────────────────────

async def run_scoring_engine():
    """
    전종목 스코어링 실행
    1. 시세 배치 다운로드
    2. 재무 스코어 (DB 캐시)
    3. 감성 스코어 (활성 종목만)
    4. 복합 스코어 계산
    5. stock_scores 저장
    """
    today = date.today()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 스코어링 엔진 시작 - {today}")

    kr_tickers, us_tickers = await load_screening_pool()
    print(f"  KR {len(kr_tickers)}종목 / US {len(us_tickers)}종목")

    # ── 재무 캐시 업데이트 (캐시 없는 종목만, 최대 30개/일) ──
    print("  재무 캐시 업데이트 중...")
    await _update_financials_cache(us_tickers[:30], kr_tickers[:20])

    # ── 시세 수집 ──
    print("  시세 수집 중...")
    kr_prices, us_prices = await asyncio.gather(
        get_kr_prices(kr_tickers),
        get_us_prices(us_tickers),
    )

    # ── 스코어 계산 + 저장 ──
    records = []
    today_date = date.today()

    # KR
    for ticker in kr_tickers:
        price_data = kr_prices.get(ticker)
        if not price_data:
            continue

        prices = price_data.get("prices_60d", [])
        # avg_volume_20d 기준으로 과거 볼륨 배열 구성 후 오늘 실제 거래량 마지막에 삽입
        avg_vol = price_data.get("avg_volume_20d", price_data.get("volume", 0))
        today_vol = price_data.get("volume", 0)
        volumes = [avg_vol] * (len(prices) - 1) + [today_vol]

        tech = calc_technical_score(prices, volumes)
        fund = await calc_fundamental_score(ticker, "KR")
        composite = calc_composite_score(tech, fund)

        records.append((
            today_date, ticker, "KR",
            tech, fund, 0.0, composite,
            price_data.get("price"),
        ))

    # US
    for ticker in us_tickers:
        price_data = us_prices.get(ticker)
        if not price_data:
            continue

        prices = price_data.get("prices_60d", [])
        volumes_val = price_data.get("volume", 0)
        avg_vol = price_data.get("avg_volume_20d", volumes_val)
        volumes = [avg_vol] * (len(prices) - 1) + [volumes_val]

        tech = calc_technical_score(prices, volumes)
        fund = await calc_fundamental_score(ticker, "US")
        composite = calc_composite_score(tech, fund)

        records.append((
            today_date, ticker, "US",
            tech, fund, 0.0, composite,
            price_data.get("price"),
        ))

    # DB 저장
    async with get_db() as conn:
        await conn.executemany(
            """INSERT INTO stock_scores
               (score_date, ticker, market, technical_score, fundamental_score,
                sentiment_score, composite_score, market_cap)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
               ON CONFLICT (score_date, ticker) DO UPDATE SET
                 technical_score = EXCLUDED.technical_score,
                 fundamental_score = EXCLUDED.fundamental_score,
                 sentiment_score = EXCLUDED.sentiment_score,
                 composite_score = EXCLUDED.composite_score,
                 market_cap = EXCLUDED.market_cap""",
            records,
        )

    print(f"  완료: {len(records)}종목 스코어 저장")
    return len(records)


# ── 업종 평균 밸류에이션 계산 (전략가용) ──────────────────────────────

async def calculate_sector_valuations():
    """financials_cache 최신 분기 기준으로 업종별 PER/PBR 중앙값 계산 → sector_valuations 저장
    평균 대신 중앙값 사용 (이상치 왜곡 방지)
    """
    today = date.today()
    async with get_db() as conn:
        rows = await conn.fetch(
            """SELECT DISTINCT ON (f.ticker, f.market)
                      f.ticker, f.market, f.per, f.pbr, c.sector
               FROM financials_cache f
               LEFT JOIN company_info c ON f.ticker = c.ticker AND f.market = c.market
               WHERE f.per IS NOT NULL OR f.pbr IS NOT NULL
               ORDER BY f.ticker, f.market, f.fiscal_quarter DESC"""
        )

    from collections import defaultdict
    sector_data: dict = defaultdict(lambda: {"per": [], "pbr": []})
    for r in rows:
        key = (r["market"], r["sector"] or "기타")
        if r["per"] and r["per"] > 0:
            sector_data[key]["per"].append(r["per"])
        if r["pbr"] and r["pbr"] > 0:
            sector_data[key]["pbr"].append(r["pbr"])

    if not sector_data:
        print("  sector_valuations: 데이터 없음 (financials_cache 적재 전)")
        return

    records = []
    for (market, sector), vals in sector_data.items():
        per_list = sorted(vals["per"])
        pbr_list = sorted(vals["pbr"])

        def median(lst):
            if not lst:
                return None
            n = len(lst)
            return lst[n // 2] if n % 2 else (lst[n // 2 - 1] + lst[n // 2]) / 2

        records.append((
            today, market, sector,
            round(sum(per_list) / len(per_list), 2) if per_list else None,
            round(median(per_list), 2) if per_list else None,
            round(sum(pbr_list) / len(pbr_list), 2) if pbr_list else None,
            round(median(pbr_list), 2) if pbr_list else None,
            len(per_list) or len(pbr_list),
        ))

    async with get_db() as conn:
        await conn.executemany(
            """INSERT INTO sector_valuations
               (calc_date, market, sector, avg_per, median_per, avg_pbr, median_pbr, stock_count)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
               ON CONFLICT (calc_date, market, sector) DO UPDATE SET
                 avg_per = EXCLUDED.avg_per, median_per = EXCLUDED.median_per,
                 avg_pbr = EXCLUDED.avg_pbr, median_pbr = EXCLUDED.median_pbr,
                 stock_count = EXCLUDED.stock_count""",
            records,
        )
    print(f"  sector_valuations: {len(records)}개 업종 계산 완료")


# ── 에이전트별 가중 스코어 조회 ────────────────────────────────────

async def get_top_stocks(agent_id: str, market: str, top_n: int = 30) -> list[dict]:
    """에이전트별 가중치 적용 → 상위 종목 반환 (현재가 포함)
    가중치는 definitions.py AgentConfig.score_weights 단일 관리 (중복 정의 제거)
    """
    from backend.agents.definitions import AGENTS as AGENT_DEFS
    agent_def = AGENT_DEFS.get(agent_id)
    weights = agent_def.score_weights if agent_def and agent_def.score_weights \
        else {"technical": 0.5, "fundamental": 0.5}
    today = date.today()

    async with get_db() as conn:
        rows = await conn.fetch(
            """SELECT s.ticker, s.technical_score, s.fundamental_score,
                      s.sentiment_score, s.market_cap, c.name, c.sector
               FROM stock_scores s
               LEFT JOIN company_info c ON s.ticker = c.ticker AND s.market = c.market
               WHERE s.score_date = $1 AND s.market = $2""",
            today, market,
        )

    results = []
    for row in rows:
        tech = row["technical_score"] or 50.0
        fund = row["fundamental_score"] or 50.0
        weighted = calc_composite_score(tech, fund, weights)
        results.append({
            "ticker": row["ticker"],
            "name": row["name"],
            "sector": row["sector"],
            "market": market,
            "technical_score": tech,
            "fundamental_score": fund,
            "agent_score": weighted,
            "price": row["market_cap"],
        })

    results.sort(key=lambda x: x["agent_score"], reverse=True)
    top = results[:top_n]

    # 실시간 현재가 보완 (market_cap에 가격이 없는 경우)
    tickers_no_price = [r["ticker"] for r in top if not r["price"]]
    if tickers_no_price:
        if market == "KR":
            prices = await get_kr_prices(tickers_no_price)
        else:
            prices = await get_us_prices(tickers_no_price)
        for r in top:
            if not r["price"] and r["ticker"] in prices:
                r["price"] = prices[r["ticker"]].get("price", 0)

    return top
