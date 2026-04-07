"""15:30 KST — KR 종가 재스코어링 (16:00 에이전트 실행 전)"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from backend.scheduler.jobs import job_rescoring

async def main():
    await job_rescoring()

if __name__ == "__main__":
    asyncio.run(main())
