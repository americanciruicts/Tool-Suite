@echo off
echo 🔍 Network Troubleshooting for BOM Tool Access
echo.

echo 🌐 Your server details:
ipconfig | findstr "IPv4"
echo.

echo 📋 Troubleshooting steps for employees:
echo.
echo 1. SAME NETWORK TEST:
echo    - Have employee try from a computer in the same office
echo    - Make sure they're on company WiFi ^(not guest WiFi^)
echo.
echo 2. PING TEST:
echo    - Employee should run: ping 192.168.1.83
echo    - If this fails, they're on a different network segment
echo.
echo 3. ALTERNATIVE PORTS:
echo    - Try: http://192.168.1.83:8080
echo    - Try: http://192.168.1.83:3000
echo.
echo 4. VPN ISSUES:
echo    - If employee is remote, VPN might block internal IPs
echo    - Try disconnecting VPN temporarily
echo.
echo 5. CORPORATE FIREWALL:
echo    - IT department might be blocking internal network access
echo    - Need to whitelist your server IP
echo.
echo 🔧 QUICK FIXES TO TRY:
echo   A^) Use ngrok: run setup-ngrok.bat
echo   B^) Create portable version: run create-portable.bat  
echo   C^) Deploy to company server/cloud
echo.
pause