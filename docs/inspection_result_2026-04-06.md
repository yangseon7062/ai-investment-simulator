# 전체 점검 결과 — 2026-04-06

## 발견 및 수정된 버그

| 구분 | 내용 | 상태 |
|---|---|---|
| DB | `investment_logs.confidence` SCHEMA_SQL 누락 (신규 설치 시 컬럼 없음) | 수정 |
| DB | `financials_cache` UNIQUE 제약 `market` 누락 → KR/US 티커 충돌 가능 | 수정 |
| DB | `ADD CONSTRAINT IF NOT EXISTS` PostgreSQL 미지원 문법 | 수정 |
| DB | `sector_valuations` 테이블 DB에 미생성 | init_db.py 실행으로 해결 |
| API | `/api/logs/postmortems/list` f-string SQL injection 잔존 | 수정 |
| 스코어링 | `financials_cache` INSERT `ON CONFLICT (ticker, fiscal_quarter)` — market 누락 | 수정 |
| 스코어링 | financials 수집 제한 (20/10개) 두 곳에 중복 적용 → 전체 수집 안 됨 | 수정 |
| 스코어링 | PBR/PER 분기 캐시로 고정 → 주가 반영 안 됨 | 일별 갱신 추가 |
| 에이전트 | `monitor_position()` 서퍼/탐색자에 VIX 노출 (`show_macro_context=False` 무시) | 수정 |
| 에이전트 | 서퍼 포지션 점검에 뉴스 섹션 포함 (forbidden) | 수정 |
| 에이전트 | 서퍼 "테제 유효성" 질문 → "기술적 신호 유효성"으로 변경 | 수정 |
| 에이전트 | 전략가 413 TPM 에러 — raw 재무제표 포함으로 토큰 초과 | raw 필드 제거 |

---

## 미해결 / 의도적으로 보류

| 구분 | 내용 | 이유 |
|---|---|---|
| 언어 혼용 | LLM이 이탈리아어·중국어·러시아어 등 섞어 출력 | Claude API 교체 시 자연 해결 예정 |
| `confidence` None | 일부 에이전트 confidence 필드 미응답 | 판단 자체에 영향 없음, Claude API 교체 후 개선 예정 |
| KR PBR None | yfinance가 KR 종목 PBR 미제공 | yfinance 한계, 대안 데이터 소스 필요 시 추후 검토 |
| `stock_scores.sentiment_score` | 항상 0, vestigial 컬럼 | 무해, 건드리지 않음 |
| `portfolio_snapshots.cash_krw` | 항상 0, vestigial | 무해, 건드리지 않음 |

---

## 데이터 수집 결과

| 항목 | 결과 |
|---|---|
| KR 종목 | 75개 (재무 캐시 73개 — 2개 yfinance 미지원) |
| US 종목 | 517개 (재무 캐시 517개) |
| ROIC 데이터 | 534개 |
| PER 데이터 | 484개 |
| sector_valuations | 8개 섹터 |
| stock_scores | 591개 |

---

## 에이전트 실행 결과

- 5개 에이전트 전부 에러 없이 완료
- 오늘 판단: 전원 **pass** (시장 국면 횡보, 데이터 초기 수집 완료 직후)
- investment_logs 정상 기록 확인

---

## 다음 확인 사항

- [ ] Render 환경변수 Groq API 키 교체
- [ ] 내일 스케줄러 자동 실행 후 로그 확인
- [ ] Claude API 크레딧 충전 후 교체
