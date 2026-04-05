"""07:30 KST — US 포지션 모니터링 (미국 장 마감 직후 테제 체크 + 매도 판단)"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from backend.scheduler.jobs import job_us_monitor

async def main():
    await job_us_monitor()

if __name__ == "__main__":
    asyncio.run(main())
