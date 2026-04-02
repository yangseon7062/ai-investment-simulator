"""
뉴스 수집
- RSS: 연합인포맥스, Reuters KR, 한국은행, Fed
- 네이버 뉴스 종목 검색 스크래핑 (국내 개별 종목)
"""

import asyncio
import httpx
import feedparser
from datetime import datetime
from bs4 import BeautifulSoup
from typing import Optional
from backend.services.groq_service import summarize_macro_news, classify_stock_news


RSS_FEEDS = {
    "연합인포맥스": "https://www.einfomax.co.kr/rss/allnews.xml",
    "Reuters_KR":   "https://kr.reuters.com/news/rss",
    "한국은행":      "https://www.bok.or.kr/portal/bbs/P0002398/list.do?menuNo=200690&pageIndex=1&searchCnd=1&searchWrd=",
    "Fed":          "https://www.federalreserve.gov/feeds/press_all.xml",
}


async def fetch_rss_news() -> list[dict]:
    """RSS 피드 수집"""
    all_news = []
    loop = asyncio.get_event_loop()

    async with httpx.AsyncClient(timeout=15) as client:
        for source, url in RSS_FEEDS.items():
            try:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                feed = await loop.run_in_executor(None, lambda r=resp.text: feedparser.parse(r))
                for entry in feed.entries[:20]:
                    all_news.append({
                        "source": source,
                        "title": entry.get("title", ""),
                        "summary": entry.get("summary", "")[:500],
                        "link": entry.get("link", ""),
                        "published": entry.get("published", datetime.now().isoformat()),
                        "type": "macro",
                    })
            except Exception:
                pass

    # Groq: 수집된 뉴스에서 매크로 시그널 추출
    macro_analysis = await summarize_macro_news(all_news)
    return all_news, macro_analysis


async def fetch_naver_stock_news(ticker: str, stock_name: str) -> list[dict]:
    """네이버 뉴스 종목 검색 스크래핑"""
    news_list = []
    try:
        query = stock_name or ticker
        url = f"https://search.naver.com/search.naver?where=news&query={query}&sort=1&pd=4"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.naver.com",
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            soup = BeautifulSoup(resp.text, "html.parser")

            articles = soup.select("div.news_wrap")[:10]
            for article in articles:
                title_el = article.select_one("a.news_tit")
                desc_el = article.select_one("div.news_dsc")
                if not title_el:
                    continue
                news_list.append({
                    "source": "네이버뉴스",
                    "ticker": ticker,
                    "title": title_el.get_text(strip=True),
                    "summary": desc_el.get_text(strip=True)[:300] if desc_el else "",
                    "link": title_el.get("href", ""),
                    "published": datetime.now().isoformat(),
                    "type": "stock",
                })
    except Exception:
        pass

    return news_list


async def fetch_all_stock_news(tickers_names: list[tuple]) -> dict:
    """
    여러 종목 뉴스 병렬 수집 [(ticker, name), ...]
    반환: {ticker: {"news": [...], "analysis": {...}}}
    """
    tasks = [fetch_naver_stock_news(ticker, name) for ticker, name in tickers_names]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Groq 분석 병렬 실행
    analysis_tasks = []
    valid_pairs = []
    for (ticker, name), result in zip(tickers_names, raw_results):
        news = result if isinstance(result, list) else []
        valid_pairs.append((ticker, news))
        analysis_tasks.append(classify_stock_news(ticker, name, news))

    analyses = await asyncio.gather(*analysis_tasks, return_exceptions=True)

    news_by_ticker = {}
    for (ticker, news), analysis in zip(valid_pairs, analyses):
        news_by_ticker[ticker] = {
            "news": news,
            "analysis": analysis if isinstance(analysis, dict) else {},
        }

    return news_by_ticker
