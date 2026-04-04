"""
종토방(네이버 종목토론실) 감성 수집
- 안정성 테스트 필요: 차단 시 빈 결과 반환
"""

import asyncio
import httpx
from bs4 import BeautifulSoup
from datetime import datetime
from backend.services.groq_service import analyze_board_sentiment


async def fetch_stockboard_posts(ticker: str, pages: int = 2) -> list[dict]:
    """네이버 종목토론실 최신 글 수집"""
    posts = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"https://finance.naver.com/item/board.naver?code={ticker}",
    }

    async with httpx.AsyncClient(timeout=10) as client:
        for page in range(1, pages + 1):
            try:
                url = f"https://finance.naver.com/item/board.naver?code={ticker}&page={page}"
                resp = await client.get(url, headers=headers)
                soup = BeautifulSoup(resp.text, "html.parser")

                rows = soup.select("tr[onmouseover]")
                for row in rows:
                    title_el = row.select_one("td.title a")
                    agree_el = row.select_one("td:nth-child(5)")
                    disagree_el = row.select_one("td:nth-child(6)")

                    if not title_el:
                        continue

                    posts.append({
                        "ticker": ticker,
                        "title": title_el.get_text(strip=True),
                        "agree": int(agree_el.get_text(strip=True) or 0) if agree_el else 0,
                        "disagree": int(disagree_el.get_text(strip=True) or 0) if disagree_el else 0,
                        "collected_at": datetime.now().isoformat(),
                    })
            except Exception:
                pass

    return posts


def calc_sentiment_score(posts: list[dict]) -> float:
    """
    종토방 감성 스코어 (-1 ~ +1)
    agree 비율 기반 단순 계산
    """
    if not posts:
        return 0.0

    total_agree = sum(p["agree"] for p in posts)
    total_disagree = sum(p["disagree"] for p in posts)
    total = total_agree + total_disagree

    if total == 0:
        return 0.0

    # -1(전부 비동의) ~ +1(전부 동의)
    return round((total_agree - total_disagree) / total, 3)


async def get_ticker_sentiment(ticker: str) -> dict:
    """
    종목 감성 스코어 반환
    - 기본: agree/disagree 카운트 기반 수치 계산
    - Groq NLP: 게시글 제목 언어 분석으로 보완
    최종 스코어 = 카운트 기반 50% + Groq NLP 50%
    """
    posts = await fetch_stockboard_posts(ticker)
    count_score = calc_sentiment_score(posts)

    # Groq NLP 감성 분석 (제목 언어 기반)
    groq_result = await analyze_board_sentiment(ticker, posts)
    groq_score = groq_result.get("sentiment_score", 0.0)

    # 두 스코어 평균
    final_score = round((count_score + groq_score) / 2, 3)

    return {
        "ticker": ticker,
        "sentiment_score": final_score,
        "count_based_score": count_score,
        "nlp_score": groq_score,
        "dominant_emotion": groq_result.get("dominant_emotion", "혼조"),
        "sentiment_summary": groq_result.get("summary", ""),
        "post_count": len(posts),
        "collected_at": datetime.now().isoformat(),
    }


async def get_bulk_sentiment(tickers: list[str]) -> dict:
    """여러 종목 감성 병렬 수집
    - 전체: 종토방 카운트 기반 스코어 (Groq 없음)
    - 상위 10개만: Groq NLP 보완 (토큰 절감)
    """
    # 1단계: 전체 종목 카운트 기반 스코어 (Groq 없음)
    async def _count_only(ticker):
        posts = await fetch_stockboard_posts(ticker)
        score = calc_sentiment_score(posts)
        return ticker, score, len(posts)

    count_results = await asyncio.gather(*[_count_only(t) for t in tickers], return_exceptions=True)

    sentiment_map = {}
    scored = []
    for r in count_results:
        if isinstance(r, tuple):
            ticker, score, cnt = r
            sentiment_map[ticker] = {"ticker": ticker, "sentiment_score": score, "post_count": cnt}
            scored.append((ticker, cnt))

    # 2단계: 게시글 많은 상위 10개만 Groq NLP 보완
    top10 = [t for t, cnt in sorted(scored, key=lambda x: x[1], reverse=True) if cnt > 0][:10]
    if top10:
        groq_tasks = [get_ticker_sentiment(t) for t in top10]
        groq_results = await asyncio.gather(*groq_tasks, return_exceptions=True)
        for ticker, result in zip(top10, groq_results):
            if isinstance(result, dict):
                sentiment_map[ticker] = result

    return sentiment_map
