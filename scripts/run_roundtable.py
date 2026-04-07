"""금요일 17:00 KST — 주간 라운드테이블 (5개 에이전트 주간 요약 + 토론)"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from backend.scheduler.jobs import job_roundtable

async def main():
    await job_roundtable()

if __name__ == "__main__":
    asyncio.run(main())
