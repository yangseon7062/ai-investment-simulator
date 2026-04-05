"""
스케줄러 (APScheduler)
- 06:30 KST: 데이터 수집 (뉴스/환율/VIX/섹터 ETF 등)
- 07:00 KST: 스코어링 엔진 + 시장 국면 감지 (US 전날 종가 포함)
- 07:30 KST: US 포지션 모니터링 (미국 장 마감 직후 테제 체크 + 매도 판단)
- 15:30 KST: KR 종가 재스코어링
- 16:00 KST: 전 에이전트 실행 (KR 매도 판단 → KR/US 신규 매수 판단)
- 금요일 17:00 KST: 주간 라운드테이블
"""

import asyncio
from datetime import datetime, date
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.services.data_fetcher import (
    get_exchange_rate, get_vix, get_fear_greed,
    get_sector_etf_returns, get_kr_market_special,
    update_stock_universe,
)
from backend.services.news_fetcher import fetch_rss_news
from backend.services.scoring import run_scoring_engine, calculate_sector_valuations
from backend.pipeline.regime_detector import run_regime_detection
from backend.agents.runner import run_all_agents
from backend.database import get_db, execute as db_execute


KR_HOLIDAYS = set()   # 실행 시 로드

WEEKDAYS = {0, 1, 2, 3, 4}   # 월~금


def is_trading_day() -> bool:
    today = date.today()
    if today.weekday() not in WEEKDAYS:
        return False
    if today.isoformat() in KR_HOLIDAYS:
        return False
    return True


# ── 06:30 데이터 수집 ──────────────────────────────────────────────

async def job_data_collect():
    if not is_trading_day():
        print("[06:30] 휴장일 - skip")
        return
    print(f"[06:30] 데이터 수집 시작 {datetime.now()}")
    try:
        await update_stock_universe()
        results = await asyncio.gather(
            fetch_rss_news(),
            get_exchange_rate(),
            get_vix(),
            get_fear_greed(),
            get_sector_etf_returns(),
            get_kr_market_special(),
            return_exceptions=True,
        )
        today = date.today()

        # 뉴스 매크로 분석 결과 DB 저장
        news_result = results[0]
        if isinstance(news_result, tuple):
            _, macro_analysis = news_result
            if isinstance(macro_analysis, dict) and macro_analysis.get("summary"):
                await db_execute(
                    """INSERT INTO market_snapshots
                       (snapshot_date, regime_kr, regime_us, macro_data, sector_data, narrative_kr)
                       VALUES ($1, '횡보', '횡보', $2, '{}', $3)
                       ON CONFLICT (snapshot_date) DO UPDATE SET
                         narrative_kr = EXCLUDED.narrative_kr""",
                    (today, '{}', macro_analysis.get("summary", "")),
                )

        # 섹터 ETF 수익률 DB 저장
        sector_result = results[4]
        if isinstance(sector_result, dict):
            from backend.config import KR_SECTOR_ETFS, US_SECTOR_ETFS
            etf_name_map = {v: k for k, v in {**KR_SECTOR_ETFS, **US_SECTOR_ETFS}.items()}
            for market, etf_data in sector_result.items():
                for etf_ticker, data in etf_data.items():
                    try:
                        await db_execute(
                            """INSERT INTO sector_etf_history
                               (record_date, market, etf_ticker, etf_name, close_price,
                                return_1d, return_5d, return_20d)
                               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                               ON CONFLICT (record_date, etf_ticker) DO UPDATE SET
                                 close_price=EXCLUDED.close_price,
                                 return_1d=EXCLUDED.return_1d,
                                 return_5d=EXCLUDED.return_5d,
                                 return_20d=EXCLUDED.return_20d""",
                            (today, market, etf_ticker,
                             etf_name_map.get(etf_ticker, etf_ticker),
                             data.get("close"), data.get("return_1d"),
                             data.get("return_5d"), data.get("return_20d")),
                        )
                    except Exception:
                        pass

        print("[06:30] 데이터 수집 완료")
    except Exception as e:
        print(f"[06:30] 오류: {e}")


# ── 07:00 스코어링 ─────────────────────────────────────────────────

async def job_scoring():
    if not is_trading_day():
        return
    print(f"[07:00] 스코어링 + 국면 감지 시작")
    try:
        await asyncio.gather(
            run_regime_detection(),
            run_scoring_engine(),
        )
        await calculate_sector_valuations()   # 스코어링 후 업종 평균 PER/PBR 계산
        print("[07:00] 스코어링 완료")
    except Exception as e:
        print(f"[07:00] 오류: {e}")


# ── 07:30 US 포지션 모니터링 (미국 장 마감 직후) ──────────────────

async def job_us_monitor():
    """미국 장 마감(06:00 KST) 후 US 보유 포지션 테제 체크 + 매도 판단"""
    if not is_trading_day():
        return
    print(f"[07:30] US 포지션 모니터링 시작")
    try:
        from backend.pipeline.position_monitor import run_position_monitor
        await run_position_monitor("US")
        print("[07:30] US 포지션 모니터링 완료")
    except Exception as e:
        print(f"[07:30] 오류: {e}")


# ── 15:30 KR 종가 재스코어링 ──────────────────────────────────────

async def job_rescoring():
    if not is_trading_day():
        return
    print(f"[15:30] KR 종가 재스코어링")
    try:
        await run_scoring_engine()
        print("[15:30] 재스코어링 완료")
    except Exception as e:
        print(f"[15:30] 오류: {e}")


# ── 16:00 전 에이전트 실행 (매도 + 매수) ──────────────────────────

async def job_evening_run():
    if not is_trading_day():
        return
    print(f"[16:00] 에이전트 실행 (매도+매수)")
    try:
        price_spikes = await check_price_spikes()  # 급락 감지 먼저
        await run_all_agents(price_spikes=price_spikes)
    except Exception as e:
        print(f"[16:00] 오류: {e}")


# ── 금요일 17:00 주간 라운드테이블 ────────────────────────────────

async def job_roundtable():
    if not is_trading_day():
        print("[금요일 17:00] 휴장일 - skip")
        return
    print(f"[금요일 17:00] 주간 라운드테이블 시작")
    try:
        from backend.pipeline.roundtable import run_roundtable
        await run_roundtable()
    except Exception as e:
        print(f"[라운드테이블] 오류: {e}")


# ── 이벤트 드리븐: 급락 체크 (16:00 모니터링에 포함) ──────────────

async def check_price_spikes() -> dict:
    """급락 15%+ 종목 감지 → 이벤트 로그 기록 + {ticker: change_pct} 반환"""
    spikes: dict = {}
    try:
        async with get_db() as conn:
            positions = [dict(r) for r in await conn.fetch(
                "SELECT DISTINCT ticker, market, agent_id FROM simulated_trades WHERE status != 'closed'"
            )]

        if not positions:
            return spikes

        from backend.services.data_fetcher import get_kr_prices, get_us_prices
        kr_tickers = [p["ticker"] for p in positions if p["market"] == "KR"]
        us_tickers = [p["ticker"] for p in positions if p["market"] == "US"]

        async def _empty():
            return {}
        results = await asyncio.gather(
            get_kr_prices(kr_tickers) if kr_tickers else _empty(),
            get_us_prices(us_tickers) if us_tickers else _empty(),
        )
        all_prices = {**results[0], **results[1]}

        seen = set()
        for pos in positions:
            price_data = all_prices.get(pos["ticker"])
            if not price_data:
                continue
            change_pct = price_data.get("change_pct", 0)
            if change_pct <= -15:
                spikes[pos["ticker"]] = change_pct
                if pos["ticker"] not in seen:
                    import json as _json
                    await db_execute(
                        """INSERT INTO event_logs (event_type, description, triggered_agents)
                           VALUES ($1, $2, $3)""",
                        (
                            "price_spike",
                            f"{pos['ticker']} {change_pct:.1f}% 급락",
                            _json.dumps([pos["agent_id"]]),
                        ),
                    )
                    print(f"  [이벤트] {pos['ticker']} {change_pct:.1f}% 급락 감지")
                    seen.add(pos["ticker"])
    except Exception as e:
        print(f"[급락체크] 오류: {e}")
    return spikes


# ── 스케줄러 설정 ──────────────────────────────────────────────────

def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

    scheduler.add_job(job_data_collect,  CronTrigger(hour=6,  minute=30, day_of_week="mon-fri"))
    scheduler.add_job(job_scoring,       CronTrigger(hour=7,  minute=0,  day_of_week="mon-fri"))
    scheduler.add_job(job_us_monitor,    CronTrigger(hour=7,  minute=30, day_of_week="mon-fri"))
    scheduler.add_job(job_rescoring,     CronTrigger(hour=15, minute=30, day_of_week="mon-fri"))
    scheduler.add_job(job_evening_run,   CronTrigger(hour=16, minute=0,  day_of_week="mon-fri"))
    scheduler.add_job(job_roundtable,    CronTrigger(hour=17, minute=0,  day_of_week="fri"))

    return scheduler
