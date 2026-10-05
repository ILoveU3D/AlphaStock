@echo off
rem Value Genie campaign monitor — hourly scheduled-task launcher.
rem One pass = gather top-up + progress log + self-retire on completion
rem (`python -m value_genie model campaign monitor`). Machine side only:
rem it never writes model.json (red line, skills/19). Process noise goes
rem to models\_monitor_task.err; the authoritative record is
rem models\_monitor.log, written by the pass itself.
cd /d "C:\Users\yukang.wang\Documents\Yearly Report\consumer-stocks-screener"
"C:\Users\yukang.wang\AppData\Local\Python\bin\python.exe" -m value_genie model campaign monitor 1>>"models\_monitor_task.err" 2>&1
