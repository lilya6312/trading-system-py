@echo off
title 个人交易系统工作台 - 停止服务
echo 正在停止交易系统服务...
powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue; if($c){$c|ForEach-Object{Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue}}"
echo 服务已停止。
pause