@echo off
echo AI 투자 시뮬레이터 — Windows 작업 스케줄러 등록
echo =====================================================

set PROJECT=C:\Users\Admin\Desktop\ai_투자
set PYTHON=py -3

:: 기존 태스크 삭제 (재등록 시 충돌 방지)
schtasks /delete /tn "AI투자_데이터수집"    /f 2>nul
schtasks /delete /tn "AI투자_US모니터링"    /f 2>nul
schtasks /delete /tn "AI투자_재스코어링"    /f 2>nul
schtasks /delete /tn "AI투자_에이전트실행"  /f 2>nul
schtasks /delete /tn "AI투자_라운드테이블"  /f 2>nul
:: 구 태스크명 정리
schtasks /delete /tn "AI투자_에이전트판단"  /f 2>nul
schtasks /delete /tn "AI투자_포지션모니터링" /f 2>nul

:: 06:30 — 데이터 수집 + 스코어링 + 국면 감지
schtasks /create /tn "AI투자_데이터수집" ^
  /tr "%PYTHON% %PROJECT%\scripts\run_data_collect.py" ^
  /sc WEEKLY /d MON,TUE,WED,THU,FRI ^
  /st 06:30 /f
echo [완료] 06:30 데이터 수집 등록

:: 07:30 — US 포지션 모니터링 (미국 장 마감 직후)
schtasks /create /tn "AI투자_US모니터링" ^
  /tr "%PYTHON% %PROJECT%\scripts\run_us_monitor.py" ^
  /sc WEEKLY /d MON,TUE,WED,THU,FRI ^
  /st 07:30 /f
echo [완료] 07:30 US 모니터링 등록

:: 15:30 — KR 종가 재스코어링
schtasks /create /tn "AI투자_재스코어링" ^
  /tr "%PYTHON% %PROJECT%\scripts\run_agents.py" ^
  /sc WEEKLY /d MON,TUE,WED,THU,FRI ^
  /st 15:30 /f
echo [완료] 15:30 KR 재스코어링 등록

:: 16:00 — 에이전트 전체 실행 (KR 매도 판단 + KR/US 신규 매수)
schtasks /create /tn "AI투자_에이전트실행" ^
  /tr "%PYTHON% %PROJECT%\scripts\run_monitor.py" ^
  /sc WEEKLY /d MON,TUE,WED,THU,FRI ^
  /st 16:00 /f
echo [완료] 16:00 에이전트 실행 등록

:: 금요일 17:00 — 주간 라운드테이블
schtasks /create /tn "AI투자_라운드테이블" ^
  /tr "%PYTHON% %PROJECT%\scripts\run_roundtable.py" ^
  /sc WEEKLY /d FRI ^
  /st 17:00 /f
echo [완료] 금요일 17:00 라운드테이블 등록

echo.
echo 등록 완료! 확인: schtasks /query /tn "AI투자*"
pause
