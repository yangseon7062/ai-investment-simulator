"""특정 에이전트만 선택 실행 (테스트용)
사용법: python scripts/run_agents_partial.py bear surfer
"""
import asyncio, sys, os, json
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from backend.database import get_db
from backend.agents.runner import run_single_agent
from backend.agents.definitions import get_agent


async def main(agent_ids: list[str]):
    today = date.today()
    async with get_db() as conn:
        snapshot = dict(await conn.fetchrow(
            "SELECT * FROM market_snapshots WHERE snapshot_date = $1", today
        ) or {})

    macro_raw = snapshot.get("macro_data", "{}")
    macro_data = json.loads(macro_raw) if isinstance(macro_raw, str) else macro_raw

    market_context = {
        "regime_kr": snapshot.get("regime_kr", "횡보"),
        "regime_us": snapshot.get("regime_us", "횡보"),
        "narrative_kr": snapshot.get("narrative_kr", ""),
        "narrative_us": snapshot.get("narrative_us", ""),
        "fear_greed": macro_data.get("fear_greed", {}),
        "vix": macro_data.get("vix", 20),
        "fred": macro_data.get("fred", {}),
        "gold_drop": macro_data.get("gold_drop", False),
        "equity_drop": macro_data.get("equity_drop", False),
        "gold_change_pct": macro_data.get("gold_change_pct", 0.0),
        "spx_change_pct": macro_data.get("spx_change_pct", 0.0),
        "changes": macro_data.get("changes", {}),
        "date": today.isoformat(),
        "price_spikes": {},
    }

    for agent_id in agent_ids:
        try:
            agent_config = get_agent(agent_id)
            print(f"\n{'='*40}")
            print(f"  [{agent_id}] 실행 중...")
            result = await run_single_agent(agent_config, market_context)
            print(f"  [{agent_id}] 완료 → {result.get('decision')} {result.get('ticker') or ''}")
        except Exception as e:
            print(f"  [{agent_id}] 오류: {e}")
            import traceback; traceback.print_exc()
        if len(agent_ids) > 1:
            await asyncio.sleep(10)


if __name__ == "__main__":
    ids = sys.argv[1:] if len(sys.argv) > 1 else ["bear", "surfer"]
    print(f"실행할 에이전트: {ids}")
    asyncio.run(main(ids))
