"""
시장 국면 감지 (KR/US 분리)
"""

import json
import asyncio
from datetime import date
from backend.services.data_fetcher import (
    get_vix, get_fear_greed, get_fred_indicators,
    get_sector_etf_returns, get_gold_equity_signal,
)
from backend.services.claude_service import detect_market_regime, generate_market_narrative
from backend.database import execute as db_execute, fetchone, get_db


async def run_regime_detection() -> dict:
    today = date.today()

    existing = await fetchone(
        "SELECT * FROM market_snapshots WHERE snapshot_date = $1", (today,)
    )
    if existing:
        return existing

    loop = asyncio.get_event_loop()
    vix, fear_greed, fred_data, sector_etfs, gold_signal = await asyncio.gather(
        get_vix(),
        get_fear_greed(),
        loop.run_in_executor(None, get_fred_indicators),
        get_sector_etf_returns(),
        get_gold_equity_signal(),
    )

    macro_data = {
        "vix": vix,
        "fear_greed": fear_greed,
        "fred": fred_data,
        "gold_drop": gold_signal.get("gold_drop", False),
        "equity_drop": gold_signal.get("equity_drop", False),
        "gold_change_pct": gold_signal.get("gold_change_pct", 0.0),
        "spx_change_pct": gold_signal.get("spx_change_pct", 0.0),
    }

    kr_regime_result, us_regime_result = await asyncio.gather(
        detect_market_regime(macro_data, sector_etfs.get("KR", {}), "KR"),
        detect_market_regime(macro_data, sector_etfs.get("US", {}), "US"),
    )

    regime_kr = kr_regime_result.get("regime", "횡보")
    regime_us = us_regime_result.get("regime", "횡보")

    narrative_kr, narrative_us = await asyncio.gather(
        generate_market_narrative(macro_data, sector_etfs.get("KR", {}), regime_kr, "KR"),
        generate_market_narrative(macro_data, sector_etfs.get("US", {}), regime_us, "US"),
    )

    await db_execute(
        """INSERT INTO market_snapshots
           (snapshot_date, regime_kr, regime_us, macro_data, sector_data,
            narrative_kr, narrative_us)
           VALUES ($1, $2, $3, $4, $5, $6, $7)
           ON CONFLICT (snapshot_date) DO UPDATE SET
             regime_kr = EXCLUDED.regime_kr,
             regime_us = EXCLUDED.regime_us,
             macro_data = EXCLUDED.macro_data,
             sector_data = EXCLUDED.sector_data,
             narrative_kr = EXCLUDED.narrative_kr,
             narrative_us = EXCLUDED.narrative_us""",
        (
            today, regime_kr, regime_us,
            json.dumps(macro_data, ensure_ascii=False),
            json.dumps(sector_etfs, ensure_ascii=False),
            narrative_kr, narrative_us,
        ),
    )

    return {
        "snapshot_date": today,
        "regime_kr": regime_kr,
        "regime_us": regime_us,
        "macro_data": macro_data,
        "sector_data": sector_etfs,
        "narrative_kr": narrative_kr,
        "narrative_us": narrative_us,
    }
