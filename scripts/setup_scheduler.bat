@echo off
echo AI 투자 시뮬레이터 — Windows 작업 스케줄러 등록
echo =====================================================

set PROJECT=C:\Users\Admin\Desktop\ai_투자
set PYTHON=py -3

:: 06:30 — 데이터 수집 + 스코어링 (Python 직접)
schtasks /create /tn "AI투자_데이터수집" ^
  /tr "%PYTHON% %PROJECT%\scripts\run_data_collect.py" ^
  /sc WEEKLY /d MON,TUE,WED,THU,FRI ^
  /st 06:30 /f
echo [완료] 06:30 데이터 수집 등록

:: 08:30 — 에이전트 판단 (Claude CLI)
schtasks /create /tn "AI투자_에이전트판단" ^
  /tr "claude --print < %PROJECT%\scripts\claude_agents_prompt.txt" ^
  /sc WEEKLY /d MON,TUE,WED,THU,FRI ^
  /st 08:30 /f
echo [완료] 08:30 에이전트 판단 등록

:: 16:00 — 포지션 모니터링 (Claude CLI)
schtasks /create /tn "AI투자_포지션모니터링" ^
  /tr "claude --print < %PROJECT%\scripts\claude_monitor_prompt.txt" ^
  /sc WEEKLY /d MON,TUE,WED,THU,FRI ^
  /st 16:00 /f
echo [완료] 16:00 포지션 모니터링 등록

echo.
echo 등록 완료! 확인: schtasks /query /tn "AI투자*"
pause
