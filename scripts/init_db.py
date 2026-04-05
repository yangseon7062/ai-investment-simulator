"""
DB 초기화 스크립트 (PostgreSQL / Neon)
- 모든 테이블 생성
- 초기 데이터 선적재 (company_info 기초값)
- 에이전트 포트폴리오 초기화 (1억원)

실행: python scripts/init_db.py [--load-stocks]
"""

import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from backend.database import get_db, close_pool


SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS agent_portfolios (
        agent_id    TEXT PRIMARY KEY,
        cash_krw    REAL DEFAULT 100000000,
        updated_at  TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS simulated_trades (
        id              SERIAL PRIMARY KEY,
        agent_id        TEXT NOT NULL,
        ticker          TEXT NOT NULL,
        market          TEXT NOT NULL CHECK(market IN ('KR','US')),
        name            TEXT,
        action          TEXT NOT NULL CHECK(action IN ('BUY','SELL','ADD')),
        price           REAL NOT NULL,
        quantity        REAL NOT NULL,
        exchange_rate   REAL,
        trade_round     INTEGER DEFAULT 1,
        log_id          INTEGER,
        highest_price   REAL,
        status          TEXT DEFAULT 'buy' CHECK(status IN ('buy','hold','watch','closed')),
        trade_date      TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS investment_logs (
        id                  SERIAL PRIMARY KEY,
        agent_id            TEXT NOT NULL,
        log_type            TEXT NOT NULL,
        decision            TEXT,
        tickers             TEXT,
        report_md           TEXT NOT NULL,
        thesis              TEXT,
        thesis_valid        BOOLEAN,
        market_regime_kr    TEXT,
        market_regime_us    TEXT,
        market_snapshot_id  INTEGER,
        created_at          TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS postmortems (
        id              SERIAL PRIMARY KEY,
        agent_id        TEXT NOT NULL,
        ticker          TEXT NOT NULL,
        buy_log_id      INTEGER,
        sell_log_id     INTEGER,
        pnl_pct         REAL,
        pnl_pct_krw     REAL,
        was_correct     BOOLEAN,
        report_md       TEXT NOT NULL,
        created_at      TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS market_snapshots (
        id              SERIAL PRIMARY KEY,
        snapshot_date   DATE UNIQUE NOT NULL,
        regime_kr       TEXT NOT NULL,
        regime_us       TEXT NOT NULL,
        macro_data      TEXT NOT NULL,
        sector_data     TEXT NOT NULL,
        kr_special      TEXT,
        narrative_kr    TEXT,
        narrative_us    TEXT,
        daily_summary   TEXT,
        created_at      TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stock_scores (
        id                  SERIAL PRIMARY KEY,
        score_date          DATE NOT NULL,
        ticker              TEXT NOT NULL,
        market              TEXT NOT NULL,
        technical_score     REAL,
        fundamental_score   REAL,
        sentiment_score     REAL,
        composite_score     REAL,
        market_cap          REAL,
        created_at          TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(score_date, ticker)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS financials_cache (
        id                  SERIAL PRIMARY KEY,
        ticker              TEXT NOT NULL,
        market              TEXT NOT NULL,
        fiscal_quarter      TEXT NOT NULL,
        revenue             REAL,
        operating_income    REAL,
        net_income          REAL,
        total_assets        REAL,
        invested_capital    REAL,
        roic                REAL,
        pbr                 REAL,
        per                 REAL,
        revenue_growth      REAL,
        gross_margin        REAL,
        fcf                 REAL,
        debt_ratio          REAL,
        updated_at          TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(ticker, fiscal_quarter)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS event_logs (
        id              SERIAL PRIMARY KEY,
        event_type      TEXT NOT NULL,
        description     TEXT,
        triggered_agents TEXT,
        created_at      TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS portfolio_snapshots (
        id              SERIAL PRIMARY KEY,
        agent_id        TEXT NOT NULL,
        snapshot_date   DATE NOT NULL,
        cash_krw        REAL NOT NULL,
        stock_value_krw REAL NOT NULL,
        total_value_krw REAL NOT NULL,
        daily_return    REAL,
        UNIQUE(agent_id, snapshot_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS api_usage (
        id              SERIAL PRIMARY KEY,
        model           TEXT NOT NULL,
        input_tokens    INTEGER,
        output_tokens   INTEGER,
        estimated_cost  REAL,
        purpose         TEXT,
        created_at      TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_etf_history (
        id              SERIAL PRIMARY KEY,
        record_date     DATE NOT NULL,
        market          TEXT NOT NULL CHECK(market IN ('KR','US')),
        etf_ticker      TEXT NOT NULL,
        etf_name        TEXT,
        close_price     REAL NOT NULL,
        return_1d       REAL,
        return_5d       REAL,
        return_20d      REAL,
        created_at      TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(record_date, etf_ticker)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS company_info (
        ticker      TEXT NOT NULL,
        market      TEXT NOT NULL CHECK(market IN ('KR','US')),
        name        TEXT NOT NULL,
        sector      TEXT,
        industry    TEXT,
        updated_at  TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (ticker, market)
    )
    """,
    # 인덱스
    "CREATE INDEX IF NOT EXISTS idx_trades_agent ON simulated_trades(agent_id)",
    "CREATE INDEX IF NOT EXISTS idx_trades_ticker ON simulated_trades(ticker)",
    "CREATE INDEX IF NOT EXISTS idx_trades_status ON simulated_trades(status)",
    "CREATE INDEX IF NOT EXISTS idx_logs_agent ON investment_logs(agent_id)",
    "CREATE INDEX IF NOT EXISTS idx_logs_type ON investment_logs(log_type)",
    "CREATE INDEX IF NOT EXISTS idx_logs_created ON investment_logs(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_scores_date ON stock_scores(score_date)",
    "CREATE INDEX IF NOT EXISTS idx_scores_ticker ON stock_scores(ticker)",
    "CREATE INDEX IF NOT EXISTS idx_snapshots_agent ON portfolio_snapshots(agent_id)",
]

AGENTS = ["macro", "strategist", "analyst", "surfer", "explorer", "contrarian", "bear"]

US_STOCKS = [
    ("AAPL", "Apple Inc.", "Technology"),
    ("MSFT", "Microsoft Corp.", "Technology"),
    ("NVDA", "NVIDIA Corp.", "Technology"),
    ("AMZN", "Amazon.com Inc.", "Consumer Cyclical"),
    ("GOOGL", "Alphabet Inc.", "Communication Services"),
    ("META", "Meta Platforms", "Communication Services"),
    ("TSLA", "Tesla Inc.", "Consumer Cyclical"),
    ("AVGO", "Broadcom Inc.", "Technology"),
    ("TSM", "Taiwan Semiconductor", "Technology"),
    ("JPM", "JPMorgan Chase", "Financial Services"),
    ("XOM", "Exxon Mobil", "Energy"),
    ("LLY", "Eli Lilly", "Healthcare"),
    ("UNH", "UnitedHealth Group", "Healthcare"),
    ("V", "Visa Inc.", "Financial Services"),
    ("MA", "Mastercard", "Financial Services"),
    ("HD", "Home Depot", "Consumer Cyclical"),
    ("PG", "Procter & Gamble", "Consumer Defensive"),
    ("COST", "Costco Wholesale", "Consumer Defensive"),
    ("NFLX", "Netflix Inc.", "Communication Services"),
    ("AMD", "Advanced Micro Devices", "Technology"),
]

KR_STOCKS = [
    ("005930", "삼성전자", "반도체"),
    ("000660", "SK하이닉스", "반도체"),
    ("035420", "NAVER", "IT/인터넷"),
    ("005380", "현대차", "자동차"),
    ("000270", "기아", "자동차"),
    ("051910", "LG화학", "화학"),
    ("006400", "삼성SDI", "2차전지"),
    ("247540", "에코프로비엠", "2차전지"),
    ("207940", "삼성바이오로직스", "바이오"),
    ("068270", "셀트리온", "바이오"),
    ("105560", "KB금융", "금융"),
    ("055550", "신한지주", "금융"),
    ("003550", "LG", "지주"),
    ("012330", "현대모비스", "자동차부품"),
    ("028260", "삼성물산", "건설/지주"),
    ("034730", "SK", "지주"),
    ("017670", "SK텔레콤", "통신"),
    ("030200", "KT", "통신"),
    ("066570", "LG전자", "전자"),
    ("009150", "삼성전기", "전자부품"),
]


MIGRATIONS = [
    # financials_cache 컬럼 추가 (기존 DB 대응)
    "ALTER TABLE financials_cache ADD COLUMN IF NOT EXISTS gross_margin REAL",
    "ALTER TABLE financials_cache ADD COLUMN IF NOT EXISTS fcf REAL",
    "ALTER TABLE financials_cache ADD COLUMN IF NOT EXISTS debt_ratio REAL",
    # investment_logs hold 타입 (CHECK 제약 없으면 자동 허용, 있으면 수정 필요)
]


async def init_db():
    async with get_db() as conn:
        print("테이블 생성 중...")
        for sql in SCHEMA_SQL:
            await conn.execute(sql)

        print("마이그레이션 적용 중...")
        for sql in MIGRATIONS:
            try:
                await conn.execute(sql)
            except Exception as e:
                print(f"  마이그레이션 스킵 (이미 적용됨): {e}")

        print("에이전트 포트폴리오 초기화 (1억원)...")
        for agent_id in AGENTS:
            await conn.execute(
                """INSERT INTO agent_portfolios (agent_id, cash_krw)
                   VALUES ($1, $2)
                   ON CONFLICT (agent_id) DO NOTHING""",
                agent_id, 100_000_000.0,
            )

    print(f"DB 초기화 완료")


async def load_initial_stocks():
    async with get_db() as conn:
        print(f"미국 종목 {len(US_STOCKS)}개 저장 중...")
        for ticker, name, sector in US_STOCKS:
            await conn.execute(
                """INSERT INTO company_info (ticker, market, name, sector)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (ticker, market) DO UPDATE SET name=$3, sector=$4""",
                ticker, "US", name, sector,
            )

        print(f"국내 종목 {len(KR_STOCKS)}개 저장 중...")
        for ticker, name, sector in KR_STOCKS:
            await conn.execute(
                """INSERT INTO company_info (ticker, market, name, sector)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (ticker, market) DO UPDATE SET name=$3, sector=$4""",
                ticker, "KR", name, sector,
            )

    print("초기 종목 데이터 로딩 완료")


async def main():
    await init_db()
    if "--load-stocks" in sys.argv:
        await load_initial_stocks()
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
