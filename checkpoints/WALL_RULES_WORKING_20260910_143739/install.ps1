$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
py -3.12 -m pip install --upgrade pip
py -3.12 -m pip install -r ".\requirements.txt"
Write-Host ""
Write-Host "3Dcad dependencies installed." -ForegroundColor Green
Write-Host "Run with: .\run.ps1"
