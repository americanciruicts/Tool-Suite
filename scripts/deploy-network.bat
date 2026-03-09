@echo off
echo 🚀 Starting BOM Comparison Tool for Internal Network Access...

REM Get the server's IP address
echo 📡 Detecting server IP address...
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4 Address"') do (
    for /f "tokens=1" %%b in ("%%a") do (
        set SERVER_IP=%%b
        goto :found_ip
    )
)

:found_ip
if "%SERVER_IP%"=="" (
    echo ❌ Could not detect IP address. Please run 'ipconfig' manually to find your IP.
    pause
    exit /b 1
)

echo 🌐 Server IP detected: %SERVER_IP%
echo.

REM Check if Docker is running
docker info >nul 2>&1
if errorlevel 1 (
    echo ❌ Docker is not running. Please start Docker and try again.
    pause
    exit /b 1
)

REM Stop existing containers if running
echo 🛑 Stopping existing containers...
docker-compose down 2>nul

REM Build containers
echo 🔨 Building containers...
docker-compose build --no-cache

REM Start services
echo 🚀 Starting services...
docker-compose up -d

REM Wait for services to start
echo ⏳ Waiting for services to start...
timeout /t 30 /nobreak >nul

REM Check service status
echo 🔍 Checking service status...
docker-compose ps

echo.
echo 🎉 Deployment complete!
echo.
echo 📊 BOM Comparison Tool is now available on the internal network:
echo    ✅ Local access:    http://localhost
echo    ✅ Network access:  http://%SERVER_IP%
echo.
echo 📧 Share this URL with employees: http://%SERVER_IP%
echo.
echo 🔧 Management commands:
echo   View logs:     docker-compose logs -f
echo   Stop services: docker-compose down
echo   Restart:       docker-compose restart
echo.
echo 📁 Data is persisted in Docker volumes
echo 📝 Logs are available in ./logs/nginx/
echo.
echo ⚠️  FIREWALL NOTE: Make sure port 80 is open on this server
echo    Windows: Windows Defender Firewall ^> Allow an app
echo    Or run: netsh advfirewall firewall add rule name="BOM Tool" dir=in action=allow protocol=TCP localport=80

pause