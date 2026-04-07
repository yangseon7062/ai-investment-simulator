"""16:00 KST — 에이전트 전체 실행 (매도 + 매수)"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from backend.scheduler.jobs import job_evening_run

async def main():
    await job_evening_run()

if __name__ == "__main__":
    asyncio.run(main())
