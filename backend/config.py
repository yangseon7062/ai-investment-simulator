import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GROQ_API_KEY      = os.getenv("GROQ_API_KEY", "")
FRED_API_KEY      = os.getenv("FRED_API_KEY", "")
DART_API_KEY      = os.getenv("DART_API_KEY", "")

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS_DIR = os.path.join(BASE_DIR, "data", "reports")

# Database (Neon PostgreSQL)
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Claude
CLAUDE_MODEL = "claude-sonnet-4-6"
CLAUDE_MAX_TOKENS = 4096

# 스크리닝 풀
KR_INDICES = ["KOSPI200", "KOSDAQ150"]
US_INDICES = ["SP500", "NASDAQ100"]

# 섹터 ETF
KR_SECTOR_ETFS = {
    "반도체":   "091160",   # TIGER 반도체
    "2차전지":  "305720",   # TIGER 2차전지테마
    "바이오":   "143860",   # TIGER 헬스케어
    "방산":     "455050",   # KODEX 방산
    "금융":     "091170",   # TIGER 은행
    "IT":       "266360",   # KODEX IT
}

US_SECTOR_ETFS = {
    "Technology":               "XLK",
    "Semiconductors":           "SMH",
    "Healthcare":               "XLV",
    "Financials":               "XLF",
    "Energy":                   "XLE",
    "Defense":                  "ITA",
    "Communication Services":   "XLC",
}

# 베어 에이전트 인버스 ETF
INVERSE_ETFS = {
    "KR_1X":  "114800",   # KODEX 인버스
    "KR_2X":  "252670",   # KODEX 200선물인버스2X
    "US_1X":  "SH",
    "US_3X":  "SQQQ",
}

# 스케줄 시간 (KST)
SCHEDULE = {
    "data_collect":     "06:30",
    "scoring":          "07:00",
    "agents_run":       "08:30",
    "kr_monitor":       "16:00",
    "us_monitor":       "07:30",   # 익일
    "roundtable":       "17:00",   # 금요일
}

# 에이전트 공통
VIRTUAL_CASH_KRW = 100_000_000   # 1억원
MAX_AGENT_MEMORY_DAYS = 30
