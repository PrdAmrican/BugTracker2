@echo off
rem SPDX-License-Identifier: AGPL-3.0-or-later
rem Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
setlocal
rem Stops the Bug Tracker server started by start_bugtracker.bat.
rem Keep PORT the same as in start_bugtracker.bat.
set "PORT=5000"

powershell -NoProfile -NonInteractive -Command ^
  "$ids = Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique;" ^
  "if (-not $ids) { Write-Host 'Bug Tracker is not running.'; exit 0 }" ^
  "foreach ($id in $ids) { $p = Get-Process -Id $id -ErrorAction SilentlyContinue;" ^
  "  if ($p -and $p.ProcessName -like 'python*') { Stop-Process -Id $id -Force; Write-Host 'Bug Tracker stopped.' }" ^
  "  elseif ($p) { Write-Host ('Port %PORT% is used by ' + $p.ProcessName + ', not Bug Tracker - left it running.') } }"

timeout /t 3 >nul
