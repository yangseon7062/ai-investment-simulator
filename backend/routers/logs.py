from fastapi import APIRouter, Query
from typing import Optional
from datetime import date
from backend.database import fetchall, fetchone

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("/")
async def get_logs(
    agent_id: Optional[str] = None,
    log_type: Optional[str] = None,
    exclude_type: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = Query(50, le=200),
):
    rows = await fetchall(
        """SELECT * FROM investment_logs
           WHERE ($1::text IS NULL OR agent_id = $1)
             AND ($2::text IS NULL OR log_type = $2)
             AND ($3::text IS NULL OR log_type != $3)
             AND ($4::date IS NULL OR created_at::date >= $4)
             AND ($5::date IS NULL OR created_at::date <= $5)
           ORDER BY created_at DESC
           LIMIT $6""",
        (agent_id, log_type, exclude_type, from_date, to_date, limit),
    )
    return [dict(r) for r in rows]


@router.get("/postmortems/list")
async def get_postmortems(agent_id: Optional[str] = None, limit: int = Query(30, le=200)):
    rows = await fetchall(
        """SELECT * FROM postmortems
           WHERE ($1::text IS NULL OR agent_id = $1)
           ORDER BY created_at DESC
           LIMIT $2""",
        (agent_id, limit),
    )
    return [dict(r) for r in rows]


@router.get("/roundtable/latest")
async def get_latest_roundtable():
    row = await fetchone(
        "SELECT * FROM investment_logs WHERE log_type = 'roundtable' ORDER BY created_at DESC LIMIT 1"
    )
    return dict(row) if row else {}


@router.get("/{log_id}")
async def get_log(log_id: int):
    row = await fetchone("SELECT * FROM investment_logs WHERE id = $1", (log_id,))
    return dict(row) if row else {}
