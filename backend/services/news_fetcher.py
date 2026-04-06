"""
뉴스 수집
- RSS: 연합인포맥스, Reuters KR, 한국은행, Fed
- 네이버 뉴스 종목 검색 스크래핑 (국내 개별 종목)
- news_articles DB 저장 (뉴스 증가율 집계용)
"""

import asyncio
import httpx
import feedparser
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from typing import Optional
from backend.services.groq_service import summarize_macro_news
from backend.database import execute as db_execute, fetchall


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

    # DB 저장 (뉴스 증가율 집계용) — 저장 실패해도 수집 결과에 영향 없음
    if news_list:
        for item in news_list:
            item["market"] = "KR"
        try:
            await save_news_to_db(news_list)
        except Exception:
            pass

    return news_list


async def save_news_to_db(articles: list[dict]):
    """
    뉴스 기사 DB 저장 (news_articles 테이블)
    중복 방지: 같은 날 동일 ticker+title은 저장하지 않음
    """
    for article in articles:
        try:
            title = article.get("title", "").strip()
            if not title:
                continue
            ticker  = article.get("ticker")
            market  = article.get("market")
            source  = article.get("source")
            pub_raw = article.get("published")
            published_at = None
            if pub_raw:
                try:
                    published_at = datetime.fromisoformat(str(pub_raw)[:19])
                except Exception:
                    published_at = datetime.now()

            await db_execute(
                """INSERT INTO news_articles (ticker, market, title, source, published_at)
                   SELECT $1, $2, $3, $4, $5
                   WHERE NOT EXISTS (
                       SELECT 1 FROM news_articles
                       WHERE ticker IS NOT DISTINCT FROM $1
                         AND title = $3
                         AND created_at >= NOW() - INTERVAL '24 hours'
                   )""",
                (ticker, market, title, source, published_at),
            )
        except Exception:
            pass


async def get_news_trend(ticker: str, market: str) -> dict:
    """
    종목별 주간 뉴스 증가율 계산
    반환: {
        "this_week": 이번주 기사 수,
        "prev_week": 지난주 기사 수,
        "growth_pct": 증가율 (%),
        "available": 데이터 존재 여부
    }
    """
    try:
        rows = await fetchall(
            """SELECT COUNT(*) as cnt,
                      CASE WHEN published_at >= NOW() - INTERVAL '7 days'
                           THEN 'this_week' ELSE 'prev_week' END as period
               FROM news_articles
               WHERE ticker = $1
                 AND (market = $2 OR market IS NULL)
                 AND published_at >= NOW() - INTERVAL '14 days'
               GROUP BY period""",
            (ticker, market),
        )
        count_map = {r["period"]: int(r["cnt"]) for r in rows}
        this_week = count_map.get("this_week", 0)
        prev_week = count_map.get("prev_week", 0)

        if this_week == 0 and prev_week == 0:
            return {"available": False}

        growth_pct = None
        if prev_week > 0:
            growth_pct = round((this_week - prev_week) / prev_week * 100, 1)
        elif this_week > 0:
            growth_pct = 100.0  # 지난주 0건 → 이번주 발생 = 100% 증가로 표현

        return {
            "available": True,
            "this_week": this_week,
            "prev_week": prev_week,
            "growth_pct": growth_pct,
        }
    except Exception:
        return {"available": False}
