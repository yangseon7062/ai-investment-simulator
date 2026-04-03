from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os

from backend.config import BASE_DIR
from backend.database import get_pool, close_pool
from backend.routers import dashboard, logs, agents
from backend.scheduler.jobs import create_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()          # 시작 시 커넥션 풀 초기화
    scheduler = create_scheduler()
    scheduler.start()
    yield
    scheduler.shutdown()
    await close_pool()        # 종료 시 풀 닫기


app = FastAPI(title="AI 투자 시뮬레이터", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router)
app.include_router(logs.router)
app.include_router(agents.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


# 프론트엔드 정적 파일
frontend_dir = os.path.join(BASE_DIR, "frontend")

if os.path.exists(frontend_dir):
    # CSS / JS / 기타 정적 에셋
    app.mount("/css", StaticFiles(directory=os.path.join(frontend_dir, "css")), name="css")
    app.mount("/js",  StaticFiles(directory=os.path.join(frontend_dir, "js")),  name="js")

    # SPA 루트 — 모든 프론트엔드 경로를 index.html 로 처리
    @app.get("/")
    async def serve_root():
        return FileResponse(os.path.join(frontend_dir, "index.html"))

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # API 경로는 위에서 이미 처리됨 — 나머지는 SPA index.html 반환
        file_path = os.path.join(frontend_dir, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(frontend_dir, "index.html"))
