@echo off
title PDF Blur + Watermark
cd /d "%~dp0"
echo Starting PDF Blur + Watermark Tool...
echo Open http://localhost:8777 in your browser
start python pdf_blur_app.py
timeout /t 3 /nobreak >nul
start http://localhost:8777
