#!/bin/bash

# Navigate to the project directory
# (Adjust this path if you move the project)
cd ~/projects/stock-ai-beast || { echo "❌ Project directory not found"; exit 1; }

# Clear terminal for clean startup
clear

# Run the PowerShell launcher via Windows executable
# This ensures we reuse the same logic (Auth, Data Checks, Docker) as the Windows side
echo "🚀 Launching Stock AI Beast..."
powershell.exe -ExecutionPolicy Bypass -File ./beast_launcher.ps1
