"""08:30 KST — 에이전트 판단 (Claude CLI로 실행)"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from backend.scheduler.jobs import job_agents

async def main():
    await job_agents()

if __name__ == "__main__":
    asyncio.run(main())
