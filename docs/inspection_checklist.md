# 전체 점검 체크리스트

> 작성일: 2026-04-06
> 점검 순서: 데이터 → 스코어링 → LLM 판단 → DB → API/프론트
> 방식: 수동 점검 (스크립트 실행 후 결과 눈으로 확인)

---

## 1단계 — 데이터 수집 품질

`python scripts/run_data_collect.py` 실행 후 확인

### 1-1. 수집 숫자
- [ ] `[종목 업데이트] KR 75개 + US 517개` 출력되는지
- [ ] 완료까지 에러 없이 진행되는지

### 1-2. 시장 데이터
DB에서 직접 확인 (`market_snapshots` 최신 행):
- [ ] `regime_kr` / `regime_us` 값이 5개 국면 중 하나인지 (상승장/하락장/횡보/변동성급등/유동성경색)
- [ ] `macro_data`에 VIX, 금리, 환율, 공포탐욕지수 들어있는지
- [ ] `narrative_kr` / `narrative_us` 텍스트 생성됐는지
- [ ] `daily_summary` 오늘 날짜로 생성됐는지

### 1-3. 섹터 ETF
`sector_etf_history` 최신 행:
- [ ] KR 6개 ETF 수익률 들어있는지 (091160, 305720, 143850, 475050, 091170, 266360)
- [ ] US 7개 ETF 수익률 들어있는지 (XLK, SMH, XLV, XLF, XLE, ITA, XLC)

### 1-4. 스코어링
`stock_scores` 오늘 날짜 행:
- [ ] KR 75개 / US 517개 행 존재하는지
- [ ] `technical_score` 범위 0~100 사이인지
- [ ] `fundamental_score` 범위 0~100 사이인지
- [ ] `composite_score` NULL 없는지

### 1-5. 재무 캐시
`financials_cache` 확인:
- [ ] 최근 업데이트 날짜 오늘인지
- [ ] `roic`, `pbr`, `per` 값 NULL 아닌 행 비율 (50% 이상이면 정상)
- [ ] KR과 US 동일 티커 충돌 없는지 (UNIQUE market+ticker+quarter)

### 1-6. 업종 평균 밸류에이션
`sector_valuations` 오늘 날짜 행:
- [ ] KR/US 각 섹터별 `median_per` / `median_pbr` 들어있는지
- [ ] 전략가용 데이터 — 적어도 10개 섹터 이상 존재하는지

---

## 2단계 — 스코어링 검증

### 2-1. 에이전트별 가중치 적용 확인
`scoring.py`에서 에이전트별 `composite_score` = technical × w_t + fundamental × w_f:

| 에이전트 | 기술 가중치 | 재무 가중치 |
|---|---|---|
| 매크로 | 0.6 | 0.4 |
| 전략가 | 0.2 | 0.8 |
| 서퍼 | 0.85 | 0.15 |
| 미래탐색자 | 0.3 | 0.7 |
| 베어 | 0.8 | 0.2 |

- [ ] 상위 종목이 각 에이전트 전략에 맞는 성격인지 눈으로 확인
  - 서퍼 상위 = 기술적 모멘텀 강한 종목
  - 전략가 상위 = ROIC 높고 밸류에이션 낮은 종목

### 2-2. 이상값 체크
- [ ] `technical_score` 0 또는 100인 종목 다수면 버그 의심
- [ ] `fundamental_score` 전부 50.0 고정이면 재무 수집 실패 의심

---

## 3단계 — LLM 판단 품질

`python scripts/run_monitor.py` 실행 후 `investment_logs` 최신 5개 에이전트 로그 확인

### 3-1. 신규 매수 판단
각 에이전트 오늘 `log_type=pass` 또는 `buy` 확인:
- [ ] 5단 구조 준수: `[결론] / [이유] / [행동] / [다음 조건] / [리스크]`
- [ ] `[후보 비교]` 섹션 존재하는지
- [ ] `confidence` 값 있는지 (`low/medium/high`)
- [ ] 언어 혼용 없는지 (한국어만)

### 3-2. 에이전트별 forbidden_topics 위반 여부
- [ ] **매크로**: 개별 종목 실적/PBR/PER 언급 없는지, ETF만 판단하는지
- [ ] **전략가**: VIX/공포탐욕지수/단기 모멘텀 언급 없는지
- [ ] **서퍼**: ROIC/PBR/PER/장기 전망 없는지, 뉴스를 근거로 쓰지 않는지
- [ ] **미래탐색자**: 단순 성장률 수치만으로 판단하지 않는지, 배당/안전마진 없는지
- [ ] **베어**: 긍정적 전망/매수 기회 언급 없는지

### 3-3. 포지션 모니터링 판단
보유 포지션 있는 에이전트의 `log_type=monitor` 로그:
- [ ] 서퍼: VIX/공포탐욕지수 미표시, 뉴스 섹션 미표시
- [ ] 미래탐색자: VIX/공포탐욕지수 미표시
- [ ] 전략가: 평일에는 모니터링 로그 없는지 (금요일만 실행)
- [ ] 베어: 21일 초과 포지션 강제 청산됐는지

### 3-4. 특수 에이전트 조건
- [ ] **베어**: 상승장 국면에서 pass 또는 현금 보유 상태인지
- [ ] **매크로**: ETF만 매수하는지 (개별 종목 없는지)
- [ ] **전략가**: 데이터 부족 시 리포트에 "역사 비교 기반" 또는 "절대 기준 사용" 명시하는지

---

## 4단계 — DB 정합성

### 4-1. simulated_trades 상태 전이
- [ ] `status` 값이 `buy/hold/watch/closed` 외 없는지
- [ ] `closed` 아닌 포지션에 `highest_price` 업데이트되는지 (서퍼 트레일링 스탑용)
- [ ] 매도된 포지션이 `closed`로 바뀌는지

### 4-2. postmortems 생성
- [ ] 매도 발생 시 자동으로 postmortem 행 생성되는지
- [ ] `pnl_pct` / `pnl_pct_krw` 모두 있는지
- [ ] `was_correct` Boolean 값 있는지

### 4-3. portfolio_snapshots 기록
- [ ] 매일 에이전트 5개 행 생성되는지
- [ ] `total_value_krw` = 누적 수익률% (양수/음수 모두 가능)
- [ ] `daily_return` NULL 아닌지

### 4-4. investment_logs
- [ ] `confidence` 컬럼 존재하는지 (`ALTER TABLE` 마이그레이션 확인)
- [ ] `log_type` 값이 허용 범위 내인지 (buy/sell/hold/pass/monitor/postmortem/debate/roundtable)

---

## 5단계 — API + 프론트엔드

서버 실행 후 확인: `uvicorn backend.main:app`

### 5-1. 주요 API 엔드포인트
- [ ] `GET /api/agents/` — 5개 에이전트 카드 데이터 반환 (today_action, confidence 포함)
- [ ] `GET /api/agents/{id}/positions` — 보유 포지션 반환
- [ ] `GET /api/agents/{id}/performance` — 수익률 히스토리 + MDD
- [ ] `GET /api/dashboard/summary` — 요약 데이터 반환
- [ ] `GET /api/logs/?limit=10` — 최근 로그 반환
- [ ] `GET /api/logs/?from_date=2026-04-01&to_date=2026-04-06` — 날짜 필터 동작
- [ ] `GET /api/logs/postmortems/list` — 사후검증 목록 반환
- [ ] `GET /api/agents/stock/{ticker}/matrix` — 종목뷰 5개 에이전트 스탠스

### 5-2. 대시보드 화면
- [ ] 에이전트 카드 5개 표시 (수익률, MDD, 보유종목수, 오늘 행동)
- [ ] 확신도 배지 표시 (low/medium/high)
- [ ] 베어 pass 시 "현금 대기" 설명 표시
- [ ] 섹터 집중도 60%+ 경고 표시 (해당 시)
- [ ] 오늘의 한 줄 요약 배너 최상단 표시

### 5-3. 로그 화면
- [ ] 날짜 필터 (from/to) 동작하는지
- [ ] 에이전트 필터 동작하는지
- [ ] 로그 카드 클릭 시 리포트 전문 표시

### 5-4. 종목뷰
- [ ] 티커 입력 → 5개 에이전트 스탠스 매트릭스 표시
- [ ] 미보유 에이전트도 표시되는지

---

## 점검 완료 기준

| 단계 | 합격 기준 |
|---|---|
| 1. 데이터 | 에러 0, KR/US 시세 정상, 거시 지표 최신값 |
| 2. 스코어링 | 이상값 없음, 에이전트별 상위 종목 전략에 부합 |
| 3. LLM 판단 | 5단 구조 준수, forbidden_topics 위반 없음, 한국어 출력 |
| 4. DB | 상태 전이 정상, postmortem 자동 생성, 일별 스냅샷 기록 |
| 5. API/프론트 | 전 엔드포인트 200 응답, 화면 정상 표시 |
