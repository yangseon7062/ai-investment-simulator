"""
스케줄러 (APScheduler)
- 06:30 KST: 데이터 수집
- 07:00 KST: 스코어링 엔진 + 시장 국면 감지
- 08:30 KST: 에이전트 실행
- 16:00 KST: KR 포지션 모니터링
- 07:30 KST 익일: US 포지션 모니터링
- 금요일 17:00 KST: 주간 라운드테이블
- 이벤트 드리븐: 연준/한은 금리결정, 급락, DART 공시
"""

import asyncio
from datetime import datetime, date
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.services.data_fetcher import (
    get_exchange_rate, get_vix, get_fear_greed,
    get_sector_etf_returns, get_kr_market_special,
)
from backend.services.news_fetcher import fetch_rss_news
from backend.services.scoring import run_scoring_engine
from backend.pipeline.regime_detector import run_regime_detection
from backend.pipeline.position_monitor import run_position_monitor
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
        print("[06:30] 휴장일 — skip")
        return
    print(f"[06:30] 데이터 수집 시작 {datetime.now()}")
    try:
        await asyncio.gather(
            fetch_rss_news(),
            get_exchange_rate(),
            get_vix(),
            get_fear_greed(),
            get_sector_etf_returns(),
            get_kr_market_special(),
        )
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
        print("[07:00] 스코어링 완료")
    except Exception as e:
        print(f"[07:00] 오류: {e}")


# ── 08:30 에이전트 실행 ─────────────────────────────────────────────

async def job_agents():
    if not is_trading_day():
        return
    print(f"[08:30] 에이전트 실행")
    try:
        await run_all_agents()
    except Exception as e:
        print(f"[08:30] 오류: {e}")


# ── 16:00 KR 포지션 모니터링 ──────────────────────────────────────

async def job_kr_monitor():
    if not is_trading_day():
        return
    print(f"[16:00] KR 포지션 모니터링")
    try:
        await run_position_monitor("KR")
    except Exception as e:
        print(f"[16:00] 오류: {e}")


# ── 07:30 US 포지션 모니터링 (익일) ───────────────────────────────

async def job_us_monitor():
    if not is_trading_day():
        return
    print(f"[07:30] US 포지션 모니터링")
    try:
        await run_position_monitor("US")
    except Exception as e:
        print(f"[07:30] 오류: {e}")


# ── 금요일 17:00 주간 라운드테이블 ────────────────────────────────

async def job_roundtable():
    print(f"[금요일 17:00] 주간 라운드테이블 시작")
    try:
        from backend.pipeline.roundtable import run_roundtable
        await run_roundtable()
    except Exception as e:
        print(f"[라운드테이블] 오류: {e}")


# ── 이벤트 드리븐: 급락 체크 (16:00 모니터링에 포함) ──────────────

async def check_price_spikes():
    """급락 15%+ 종목 감지 → 이벤트 로그 기록"""
    try:
        async with get_db() as conn:
            positions = [dict(r) for r in await conn.fetch(
                "SELECT DISTINCT ticker, market, agent_id FROM simulated_trades WHERE status != 'closed'"
            )]

        if not positions:
            return

        from backend.services.data_fetcher import get_kr_prices, get_us_prices
        kr_tickers = [p["ticker"] for p in positions if p["market"] == "KR"]
        us_tickers = [p["ticker"] for p in positions if p["market"] == "US"]

        results = await asyncio.gather(
            get_kr_prices(kr_tickers) if kr_tickers else asyncio.coroutine(lambda: {})(),
            get_us_prices(us_tickers) if us_tickers else asyncio.coroutine(lambda: {})(),
        )
        all_prices = {**results[0], **results[1]}

        for pos in positions:
            price_data = all_prices.get(pos["ticker"])
            if not price_data:
                continue
            change_pct = price_data.get("change_pct", 0)
            if change_pct <= -15:
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
                print(f"  [이벤트] {pos['ticker']} {change_pct:.1f}% 급락 — {pos['agent_id']} 즉시 모니터링")
    except Exception as e:
        print(f"[급락체크] 오류: {e}")


# ── 스케줄러 설정 ──────────────────────────────────────────────────

def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

    scheduler.add_job(job_data_collect,  CronTrigger(hour=6,  minute=30, day_of_week="mon-fri"))
    scheduler.add_job(job_scoring,       CronTrigger(hour=7,  minute=0,  day_of_week="mon-fri"))
    scheduler.add_job(job_us_monitor,    CronTrigger(hour=7,  minute=30, day_of_week="mon-fri"))
    scheduler.add_job(job_agents,        CronTrigger(hour=8,  minute=30, day_of_week="mon-fri"))
    scheduler.add_job(job_kr_monitor,    CronTrigger(hour=16, minute=0,  day_of_week="mon-fri"))
    scheduler.add_job(job_roundtable,    CronTrigger(hour=17, minute=0,  day_of_week="fri"))

    return scheduler
