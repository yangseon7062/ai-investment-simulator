"""06:30 KST — 데이터 수집 + 스코어링 + 국면 감지"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from backend.scheduler.jobs import job_data_collect, job_scoring

async def main():
    await job_data_collect()
    await job_scoring()

if __name__ == "__main__":
    asyncio.run(main())
