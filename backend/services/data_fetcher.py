"""
시세·재무 데이터 수집
- yfinance: 미국 종목, ETF, 환율, VIX
- pykrx: 국내 종목, 외국인 수급, 섹터 ETF
- FinanceDataReader: 국내 종목 히스토리
- FRED: 미국 경제지표
- alternative.me: 공포탐욕지수
"""

import asyncio
import httpx
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
from fredapi import Fred

from backend.config import FRED_API_KEY, KR_SECTOR_ETFS, US_SECTOR_ETFS


# ── 환율 ──────────────────────────────────────────────────────────
async def get_exchange_rate() -> float:
    """원달러 환율 (전일 종가)"""
    loop = asyncio.get_event_loop()
    ticker = await loop.run_in_executor(None, lambda: yf.Ticker("KRW=X"))
    hist = await loop.run_in_executor(None, lambda: ticker.history(period="2d"))
    if hist.empty:
        return 1300.0
    return float(hist["Close"].iloc[-1])


# ── VIX ──────────────────────────────────────────────────────────
async def get_vix() -> float:
    loop = asyncio.get_event_loop()
    ticker = await loop.run_in_executor(None, lambda: yf.Ticker("^VIX"))
    hist = await loop.run_in_executor(None, lambda: ticker.history(period="2d"))
    if hist.empty:
        return 20.0
    return float(hist["Close"].iloc[-1])


# ── 공포탐욕지수 ───────────────────────────────────────────────────
async def get_fear_greed() -> dict:
    """alternative.me Fear & Greed Index"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://api.alternative.me/fng/?limit=2")
            data = resp.json()["data"]
            return {
                "value": int(data[0]["value"]),
                "label": data[0]["value_classification"],
                "prev_value": int(data[1]["value"]),
            }
    except Exception:
        return {"value": 50, "label": "Neutral", "prev_value": 50}


# ── 미국 경제지표 (FRED) ────────────────────────────────────────────
def get_fred_indicators() -> dict:
    """주요 경제지표 최신값"""
    if not FRED_API_KEY:
        return {}
    try:
        fred = Fred(api_key=FRED_API_KEY)
        indicators = {
            "FED_RATE":    "FEDFUNDS",
            "CPI_YOY":     "CPIAUCSL",
            "UNEMPLOYMENT": "UNRATE",
            "GDP_GROWTH":  "A191RL1Q225SBEA",
            "10Y_YIELD":   "DGS10",
            "2Y_YIELD":    "DGS2",
            "HY_SPREAD":   "BAMLH0A0HYM2",   # HY OAS: 하이일드 크레딧 스프레드 (베어 핵심 지표)
            "IG_SPREAD":   "BAMLC0A0CM",      # IG OAS: 투자등급 크레딧 스프레드
        }
        result = {}
        for key, series_id in indicators.items():
            try:
                series = fred.get_series(series_id, observation_start=(datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"))
                if not series.empty:
                    result[key] = float(series.iloc[-1])
            except Exception:
                pass
        return result
    except Exception:
        return {}


# ── 미국 종목 시세 ──────────────────────────────────────────────────
async def get_us_prices(tickers: list[str]) -> dict:
    """미국 종목 전일 종가 + 기본 지표"""
    loop = asyncio.get_event_loop()

    def _fetch():
        data = yf.download(tickers, period="60d", auto_adjust=True, progress=False)
        return data

    df = await loop.run_in_executor(None, _fetch)
    result = {}

    if isinstance(df.columns, pd.MultiIndex):
        close = df["Close"]
        volume = df["Volume"]
        open_prices = df.get("Open", pd.DataFrame())
    else:
        close = df[["Close"]]
        volume = df[["Volume"]]
        open_prices = df[["Open"]] if "Open" in df.columns else pd.DataFrame()

    for ticker in tickers:
        try:
            prices = close[ticker].dropna()
            vols = volume[ticker].dropna()
            if len(prices) < 2:
                continue
            # gap % = (당일 시가 - 전일 종가) / 전일 종가 * 100
            gap_pct = None
            try:
                if not open_prices.empty and ticker in open_prices.columns:
                    today_open = float(open_prices[ticker].dropna().iloc[-1])
                    prev_close = float(prices.iloc[-2])
                    if prev_close > 0:
                        gap_pct = round((today_open - prev_close) / prev_close * 100, 2)
            except Exception:
                pass
            result[ticker] = {
                "price": float(prices.iloc[-1]),
                "prev_price": float(prices.iloc[-2]),
                "change_pct": float((prices.iloc[-1] - prices.iloc[-2]) / prices.iloc[-2] * 100),
                "volume": float(vols.iloc[-1]),
                "avg_volume_20d": float(vols.iloc[-20:].mean()),
                "prices_60d": prices.tolist(),
                "gap_pct": gap_pct,
            }
        except Exception:
            pass
    return result


# ── 국내 종목 시세 ──────────────────────────────────────────────────
async def get_kr_prices(tickers: list[str]) -> dict:
    """국내 종목 전일 종가 (pykrx)"""
    loop = asyncio.get_event_loop()

    def _fetch():
        try:
            from pykrx import stock as krx
            result = {}
            today = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
            for ticker in tickers:
                try:
                    df = krx.get_market_ohlcv(start, today, ticker)
                    if df.empty:
                        continue
                    prices = df["종가"].dropna()
                    vols = df["거래량"].dropna()
                    # gap % = (당일 시가 - 전일 종가) / 전일 종가 * 100
                    gap_pct = None
                    try:
                        opens = df["시가"].dropna()
                        if len(opens) > 1 and len(prices) > 1:
                            today_open = float(opens.iloc[-1])
                            prev_close = float(prices.iloc[-2])
                            if prev_close > 0:
                                gap_pct = round((today_open - prev_close) / prev_close * 100, 2)
                    except Exception:
                        pass
                    result[ticker] = {
                        "price": float(prices.iloc[-1]),
                        "prev_price": float(prices.iloc[-2]) if len(prices) > 1 else float(prices.iloc[-1]),
                        "change_pct": float((prices.iloc[-1] - prices.iloc[-2]) / prices.iloc[-2] * 100) if len(prices) > 1 else 0.0,
                        "volume": float(vols.iloc[-1]),
                        "avg_volume_20d": float(vols.iloc[-20:].mean()),
                        "prices_60d": prices.tolist(),
                        "gap_pct": gap_pct,
                    }
                except Exception:
                    pass
            return result
        except ImportError:
            return {}

    return await loop.run_in_executor(None, _fetch)


# ── 외국인 수급 ────────────────────────────────────────────────────
async def get_foreign_buying(tickers: list[str]) -> dict:
    """pykrx 외국인+기관 순매수 (최근 3일)"""
    loop = asyncio.get_event_loop()

    def _fetch():
        try:
            from pykrx import stock as krx
            result = {}
            today = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
            for ticker in tickers:
                try:
                    df = krx.get_market_trading_value_by_investor(start, today, ticker)
                    if df.empty:
                        continue
                    # 최근 3일 합산
                    recent = df.tail(3)
                    foreign_net = float(recent["외국인합계"].sum()) if "외국인합계" in recent else 0.0
                    inst_net = float(recent["기관합계"].sum()) if "기관합계" in recent else 0.0
                    result[ticker] = {
                        "foreign_net_3d": round(foreign_net / 1e8, 2),  # 억원
                        "institution_net_3d": round(inst_net / 1e8, 2),  # 억원
                    }
                except Exception:
                    pass
            return result
        except ImportError:
            return {}

    return await loop.run_in_executor(None, _fetch)


async def get_kr_supply_demand(tickers: list[str]) -> dict:
    """KR 종목 외국인+기관 수급 (get_foreign_buying alias)"""
    return await get_foreign_buying(tickers)


async def get_52week_high_low(tickers: list[str], market: str) -> dict:
    """52주 고저가 및 현재가 대비 위치"""
    loop = asyncio.get_event_loop()

    def _fetch():
        result = {}
        for ticker in tickers:
            try:
                t = ticker if market == "US" else ticker + ".KS"
                info = yf.Ticker(t).fast_info
                high52 = getattr(info, "fifty_two_week_high", None)
                low52 = getattr(info, "fifty_two_week_low", None)
                current = getattr(info, "last_price", None)
                if high52 and low52 and current:
                    pct_from_high = round((current - high52) / high52 * 100, 1)
                    pct_from_low = round((current - low52) / low52 * 100, 1)
                    result[ticker] = {
                        "high_52w": high52,
                        "low_52w": low52,
                        "pct_from_high": pct_from_high,  # 음수 = 고점 대비 하락
                        "pct_from_low": pct_from_low,    # 양수 = 저점 대비 상승
                    }
            except Exception:
                pass
        return result

    return await loop.run_in_executor(None, _fetch)


# ── 섹터 ETF 수익률 ────────────────────────────────────────────────
async def get_sector_etf_returns() -> dict:
    """국내·미국 섹터 ETF 수익률"""
    result = {"KR": {}, "US": {}}

    # 미국 섹터 ETF
    us_tickers = list(US_SECTOR_ETFS.values())
    loop = asyncio.get_event_loop()

    def _fetch_us():
        df = yf.download(us_tickers, period="30d", auto_adjust=True, progress=False)
        out = {}
        close = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]]
        for ticker in us_tickers:
            try:
                prices = close[ticker].dropna()
                if len(prices) < 2:
                    continue
                out[ticker] = {
                    "return_1d": float((prices.iloc[-1] - prices.iloc[-2]) / prices.iloc[-2] * 100),
                    "return_5d": float((prices.iloc[-1] - prices.iloc[-6]) / prices.iloc[-6] * 100) if len(prices) > 5 else None,
                    "return_20d": float((prices.iloc[-1] - prices.iloc[-21]) / prices.iloc[-21] * 100) if len(prices) > 20 else None,
                    "close": float(prices.iloc[-1]),
                }
            except Exception:
                pass
        return out

    result["US"] = await loop.run_in_executor(None, _fetch_us)

    # 국내 섹터 ETF
    def _fetch_kr():
        try:
            from pykrx import stock as krx
            out = {}
            today = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
            for sector, ticker in KR_SECTOR_ETFS.items():
                try:
                    df = krx.get_market_ohlcv(start, today, ticker)
                    if df.empty:
                        continue
                    prices = df["종가"].dropna()
                    out[ticker] = {
                        "sector": sector,
                        "return_1d": float((prices.iloc[-1] - prices.iloc[-2]) / prices.iloc[-2] * 100) if len(prices) > 1 else None,
                        "return_5d": float((prices.iloc[-1] - prices.iloc[-6]) / prices.iloc[-6] * 100) if len(prices) > 5 else None,
                        "return_20d": float((prices.iloc[-1] - prices.iloc[-21]) / prices.iloc[-21] * 100) if len(prices) > 20 else None,
                        "close": float(prices.iloc[-1]),
                    }
                except Exception:
                    pass
            return out
        except ImportError:
            return {}

    result["KR"] = await loop.run_in_executor(None, _fetch_kr)
    return result


# ── 재무 데이터 (ROIC 계산 포함) ──────────────────────────────────
async def get_us_financials(ticker: str) -> Optional[dict]:
    """yfinance 재무제표 → ROIC 직접 계산"""
    loop = asyncio.get_event_loop()

    def _fetch():
        try:
            t = yf.Ticker(ticker)
            income = t.quarterly_financials
            balance = t.quarterly_balance_sheet

            if income.empty or balance.empty:
                return None

            operating_income = float(income.loc["Operating Income"].iloc[0]) if "Operating Income" in income.index else None
            revenue = float(income.loc["Total Revenue"].iloc[0]) if "Total Revenue" in income.index else None
            net_income = float(income.loc["Net Income"].iloc[0]) if "Net Income" in income.index else None
            total_assets = float(balance.loc["Total Assets"].iloc[0]) if "Total Assets" in balance.index else None
            total_debt = float(balance.loc["Total Debt"].iloc[0]) if "Total Debt" in balance.index else 0
            stockholders_equity = float(balance.loc["Stockholders Equity"].iloc[0]) if "Stockholders Equity" in balance.index else None

            # ROIC = Operating Income / (Total Debt + Stockholders Equity)
            invested_capital = (total_debt or 0) + (stockholders_equity or 0)
            roic = float(operating_income / invested_capital * 100) if (operating_income and invested_capital and invested_capital != 0) else None

            info = t.info
            pbr = info.get("priceToBook")
            per = info.get("trailingPE")

            # 매출 성장률 (전년 동기 대비)
            revenue_growth = None
            if "Total Revenue" in income.index and len(income.columns) >= 5:
                rev_now = float(income.loc["Total Revenue"].iloc[0])
                rev_prev = float(income.loc["Total Revenue"].iloc[4])
                if rev_prev != 0:
                    revenue_growth = float((rev_now - rev_prev) / abs(rev_prev) * 100)

            # Gross Margin (매출총이익률)
            gross_margin = None
            if "Gross Profit" in income.index and revenue and revenue != 0:
                gross_profit = float(income.loc["Gross Profit"].iloc[0])
                gross_margin = float(gross_profit / revenue * 100)

            # FCF (잉여현금흐름) = 영업현금흐름 - 설비투자
            fcf = None
            try:
                cashflow = t.quarterly_cashflow
                if not cashflow.empty:
                    op_cf_key = next((k for k in ["Operating Cash Flow", "Total Cash From Operating Activities"] if k in cashflow.index), None)
                    capex_key = next((k for k in ["Capital Expenditure", "Capital Expenditures"] if k in cashflow.index), None)
                    if op_cf_key:
                        op_cf = float(cashflow.loc[op_cf_key].iloc[0])
                        capex = float(cashflow.loc[capex_key].iloc[0]) if capex_key else 0
                        fcf = float(op_cf + capex)  # capex는 음수로 기록됨
            except Exception:
                pass

            # Debt Ratio (부채비율) = Total Debt / Stockholders Equity
            debt_ratio = None
            if total_debt and stockholders_equity and stockholders_equity != 0:
                debt_ratio = float(total_debt / stockholders_equity * 100)

            return {
                "revenue": revenue,
                "operating_income": operating_income,
                "net_income": net_income,
                "total_assets": total_assets,
                "invested_capital": invested_capital if invested_capital else None,
                "roic": roic,
                "pbr": float(pbr) if pbr else None,
                "per": float(per) if per else None,
                "revenue_growth": revenue_growth,
                "gross_margin": gross_margin,
                "fcf": fcf,
                "debt_ratio": debt_ratio,
            }
        except Exception:
            return None

    return await loop.run_in_executor(None, _fetch)


# ── 금·주식 동반 하락 시그널 (유동성 경색 감지) ─────────────────────
async def get_gold_equity_signal() -> dict:
    """
    금(GLD)과 주식(^GSPC, ^KS11) 동반 하락 여부 체크
    반환: {"gold_drop": bool, "equity_drop": bool, "gold_change_pct": float, "spx_change_pct": float}
    """
    loop = asyncio.get_event_loop()

    def _fetch():
        try:
            data = yf.download(["GLD", "^GSPC"], period="3d", auto_adjust=True, progress=False)
            close = data["Close"] if isinstance(data.columns, pd.MultiIndex) else data
            result = {}
            for ticker in ["GLD", "^GSPC"]:
                try:
                    prices = close[ticker].dropna()
                    if len(prices) < 2:
                        result[ticker] = 0.0
                    else:
                        result[ticker] = float((prices.iloc[-1] - prices.iloc[-2]) / prices.iloc[-2] * 100)
                except Exception:
                    result[ticker] = 0.0
            return result
        except Exception:
            return {"GLD": 0.0, "^GSPC": 0.0}

    changes = await loop.run_in_executor(None, _fetch)
    gold_chg = changes.get("GLD", 0.0)
    spx_chg = changes.get("^GSPC", 0.0)

    return {
        "gold_drop": gold_chg < -1.0,
        "equity_drop": spx_chg < -1.0,
        "gold_change_pct": round(gold_chg, 2),
        "spx_change_pct": round(spx_chg, 2),
    }


# ── 한국 시장 특수 요소 ─────────────────────────────────────────────
async def get_kr_market_special() -> dict:
    """선물 만기일 여부 등 (간단 체크)"""
    today = datetime.now()
    # 매월 두번째 목요일 = 선물 만기일 (근사치)
    is_futures_expiry = False
    if today.weekday() == 3:  # 목요일
        week_of_month = (today.day - 1) // 7 + 1
        if week_of_month == 2:
            is_futures_expiry = True

    return {
        "is_futures_expiry": is_futures_expiry,
        "date": today.strftime("%Y-%m-%d"),
    }


async def update_stock_universe():
    """KOSPI200 + KOSDAQ150 + S&P500 + NASDAQ100 전종목 company_info 업데이트"""
    import requests
    from backend.database import get_db
    from pykrx import stock as krx

    loop = asyncio.get_event_loop()

    # 최근 거래일 계산 (오늘이 주말이면 금요일)
    def _last_trading_date():
        from datetime import date, timedelta
        d = date.today()
        while d.weekday() >= 5:  # 토=5, 일=6
            d -= timedelta(days=1)
        return d.strftime("%Y%m%d")

    # KR 종목 (KOSPI200 + KOSDAQ150 주요 종목 — 분기별 수동 업데이트)
    KR_UNIVERSE = {
        # 반도체
        "005930": "삼성전자", "000660": "SK하이닉스", "009150": "삼성전기",
        "042700": "한미반도체", "091990": "셀트리온헬스케어", "005290": "동진쎄미켐",
        # 2차전지
        "006400": "삼성SDI", "051910": "LG화학", "247540": "에코프로비엠",
        "373220": "LG에너지솔루션", "096770": "SK이노베이션", "011790": "SKC",
        "086520": "에코프로", "316140": "우리금융지주",
        # 자동차
        "005380": "현대차", "000270": "기아", "012330": "현대모비스",
        "064960": "S&T모티브", "161390": "한국타이어앤테크놀로지",
        # IT/인터넷
        "035420": "NAVER", "035720": "카카오", "259960": "크래프톤",
        "036570": "엔씨소프트", "263750": "펄어비스",
        # 바이오
        "207940": "삼성바이오로직스", "068270": "셀트리온", "128940": "한미약품",
        "000100": "유한양행", "185750": "종근당", "001700": "신일제약",
        "326030": "SK바이오팜", "302440": "SK바이오사이언스",
        # 금융
        "105560": "KB금융", "055550": "신한지주", "086790": "하나금융지주",
        "010950": "S-Oil", "316140": "우리금융지주", "024110": "기업은행",
        "138930": "BNK금융지주", "175330": "JB금융지주",
        # 지주/대기업
        "003550": "LG", "034730": "SK", "028260": "삼성물산",
        "000810": "삼성화재", "032830": "삼성생명",
        # 통신
        "017670": "SK텔레콤", "030200": "KT", "032640": "LG유플러스",
        # 전자/부품
        "066570": "LG전자", "006800": "미래에셋증권", "010140": "삼성중공업",
        "009540": "HD한국조선해양", "329180": "HD현대중공업",
        # 방산
        "012450": "한화에어로스페이스", "047810": "한국항공우주", "064350": "현대로템",
        # 화학/소재
        "011170": "롯데케미칼", "010060": "OCI", "298000": "효성첨단소재",
        # 유통/소비
        "004170": "신세계", "023530": "롯데쇼핑", "139480": "이마트",
        # 건설
        "000720": "현대건설", "006360": "GS건설", "047040": "대우건설",
        # KOSDAQ 대표
        "357780": "솔브레인", "403870": "HPSP", "196170": "알테오젠",
        "214150": "클래시스", "145020": "휴젤", "066970": "엘앤에프",
        "293490": "카카오게임즈", "112040": "위메이드", "251270": "넷마블",
        "950130": "엑세스바이오", "078600": "대주전자재료",
    }
    def _fetch_kr():
        return KR_UNIVERSE

    # US 종목 (S&P500 + NASDAQ100) — Wikipedia with User-Agent
    def _fetch_us():
        tickers = {}
        headers = {"User-Agent": "Mozilla/5.0 (compatible; research-bot/1.0)"}
        try:
            import io
            r = requests.get(
                "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                headers=headers, timeout=15
            )
            tables = pd.read_html(io.StringIO(r.text))
            sp500 = tables[0]
            for _, row in sp500.iterrows():
                tickers[str(row["Symbol"]).replace(".", "-")] = str(row["Security"])
        except Exception:
            pass
        try:
            import io
            r = requests.get(
                "https://en.wikipedia.org/wiki/Nasdaq-100",
                headers=headers, timeout=15
            )
            tables = pd.read_html(io.StringIO(r.text))
            # 티커 컬럼 있는 테이블 찾기
            for t in tables:
                cols = [str(c).lower() for c in t.columns]
                if "ticker" in cols or "symbol" in cols:
                    col = "Ticker" if "Ticker" in t.columns else "Symbol"
                    name_col = "Company" if "Company" in t.columns else t.columns[1]
                    for _, row in t.iterrows():
                        sym = str(row[col]).replace(".", "-")
                        if len(sym) <= 5 and sym.isalpha():
                            tickers[sym] = str(row[name_col])
                    break
        except Exception:
            pass
        return tickers

    kr_tickers = await loop.run_in_executor(None, _fetch_kr)
    us_tickers = await loop.run_in_executor(None, _fetch_us)

    async with get_db() as conn:
        for ticker, name in kr_tickers.items():
            await conn.execute(
                """INSERT INTO company_info (ticker, market, name)
                   VALUES ($1, 'KR', $2)
                   ON CONFLICT (ticker, market) DO UPDATE SET name=$2, updated_at=NOW()""",
                ticker, name,
            )
        for ticker, name in us_tickers.items():
            await conn.execute(
                """INSERT INTO company_info (ticker, market, name)
                   VALUES ($1, 'US', $2)
                   ON CONFLICT (ticker, market) DO UPDATE SET name=$2, updated_at=NOW()""",
                ticker, name,
            )

    print(f"[종목 업데이트] KR {len(kr_tickers)}개 + US {len(us_tickers)}개")


async def get_yfinance_news(tickers: list[str]) -> dict:
    """yfinance 뉴스 수집 — 미국 종목별 최신 뉴스 3개
    반환: {ticker: [{"title": str, "summary": str, "published": str}]}
    """
    loop = asyncio.get_event_loop()

    def _fetch(ticker):
        try:
            t = yf.Ticker(ticker)
            news = t.news or []
            result = []
            for item in news[:3]:
                content = item.get("content", {})
                title = content.get("title", "") or item.get("title", "")
                summary = content.get("summary", "") or ""
                pub = content.get("pubDate", "") or item.get("providerPublishTime", "")
                if title:
                    result.append({
                        "title": title,
                        "summary": summary[:300],
                        "published": str(pub),
                    })
            return ticker, result
        except Exception:
            return ticker, []

    tasks = [loop.run_in_executor(None, _fetch, t) for t in tickers]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    news_map = {}
    for r in results:
        if isinstance(r, tuple):
            ticker, news = r
            if news:
                news_map[ticker] = news

    return news_map
