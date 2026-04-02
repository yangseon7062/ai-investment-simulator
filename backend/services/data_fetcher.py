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
            "FED_RATE":  "FEDFUNDS",
            "CPI_YOY":   "CPIAUCSL",
            "UNEMPLOYMENT": "UNRATE",
            "GDP_GROWTH": "A191RL1Q225SBEA",
            "10Y_YIELD": "DGS10",
            "2Y_YIELD":  "DGS2",
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
    else:
        close = df[["Close"]]
        volume = df[["Volume"]]

    for ticker in tickers:
        try:
            prices = close[ticker].dropna()
            vols = volume[ticker].dropna()
            if len(prices) < 2:
                continue
            result[ticker] = {
                "price": float(prices.iloc[-1]),
                "prev_price": float(prices.iloc[-2]),
                "change_pct": float((prices.iloc[-1] - prices.iloc[-2]) / prices.iloc[-2] * 100),
                "volume": float(vols.iloc[-1]),
                "avg_volume_20d": float(vols.iloc[-20:].mean()),
                "prices_60d": prices.tolist(),
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
                    result[ticker] = {
                        "price": float(prices.iloc[-1]),
                        "prev_price": float(prices.iloc[-2]) if len(prices) > 1 else float(prices.iloc[-1]),
                        "change_pct": float((prices.iloc[-1] - prices.iloc[-2]) / prices.iloc[-2] * 100) if len(prices) > 1 else 0.0,
                        "volume": float(vols.iloc[-1]),
                        "avg_volume_20d": float(vols.iloc[-20:].mean()),
                        "prices_60d": prices.tolist(),
                    }
                except Exception:
                    pass
            return result
        except ImportError:
            return {}

    return await loop.run_in_executor(None, _fetch)


# ── 외국인 수급 ────────────────────────────────────────────────────
async def get_foreign_buying(tickers: list[str]) -> dict:
    """pykrx 외국인 순매수"""
    loop = asyncio.get_event_loop()

    def _fetch():
        try:
            from pykrx import stock as krx
            result = {}
            today = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=5)).strftime("%Y%m%d")
            for ticker in tickers:
                try:
                    df = krx.get_market_trading_value_by_investor(start, today, ticker)
                    if df.empty:
                        continue
                    foreign_net = float(df["외국인합계"].iloc[-1])
                    result[ticker] = {"foreign_net_buy": foreign_net}
                except Exception:
                    pass
            return result
        except ImportError:
            return {}

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
