@echo off
chcp 65001 >nul
cd /d "%~dp0nipa"
python nipa_crawler.py %*
python build_dashboard.py
