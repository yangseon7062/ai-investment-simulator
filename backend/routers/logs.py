from fastapi import APIRouter, Query
from typing import Optional
from backend.database import fetchall, fetchone

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("/")
async def get_logs(
    agent_id: Optional[str] = None,
    log_type: Optional[str] = None,
    limit: int = Query(50, le=200),
):
    conditions = []
    params = []
    if agent_id:
        conditions.append(f"agent_id = ${len(params) + 1}")
        params.append(agent_id)
    if log_type:
        conditions.append(f"log_type = ${len(params) + 1}")
        params.append(log_type)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)
    rows = await fetchall(
        f"SELECT * FROM investment_logs {where} ORDER BY created_at DESC LIMIT ${len(params)}",
        tuple(params),
    )
    return [dict(r) for r in rows]


@router.get("/{log_id}")
async def get_log(log_id: int):
    row = await fetchone("SELECT * FROM investment_logs WHERE id = $1", (log_id,))
    return dict(row) if row else {}


@router.get("/postmortems/list")
async def get_postmortems(agent_id: Optional[str] = None, limit: int = 30):
    params = []
    where = ""
    if agent_id:
        params.append(agent_id)
        where = f"WHERE agent_id = ${len(params)}"
    params.append(limit)
    rows = await fetchall(
        f"SELECT * FROM postmortems {where} ORDER BY created_at DESC LIMIT ${len(params)}",
        tuple(params),
    )
    return [dict(r) for r in rows]


@router.get("/roundtable/latest")
async def get_latest_roundtable():
    row = await fetchone(
        "SELECT * FROM investment_logs WHERE log_type = 'roundtable' ORDER BY created_at DESC LIMIT 1"
    )
    return dict(row) if row else {}
