@echo off
echo 📦 Creating portable BOM Comparison Tool...
echo.

REM Create portable directory
if not exist "BOM-Tool-Portable" mkdir "BOM-Tool-Portable"

REM Copy essential files
echo 📁 Copying files...
xcopy /E /I /H /Y "docker-compose.yml" "BOM-Tool-Portable\"
xcopy /E /I /H /Y "Dockerfile.frontend" "BOM-Tool-Portable\"
xcopy /E /I /H /Y "Dockerfile.backend" "BOM-Tool-Portable\"
xcopy /E /I /H /Y "nginx" "BOM-Tool-Portable\nginx\"
xcopy /E /I /H /Y "api" "BOM-Tool-Portable\api\"
xcopy /E /I /H /Y "app" "BOM-Tool-Portable\app\"
xcopy /E /I /H /Y "components" "BOM-Tool-Portable\components\"
xcopy /E /I /H /Y "public" "BOM-Tool-Portable\public\"
xcopy /E /I /H /Y "src" "BOM-Tool-Portable\src\"
copy "package.json" "BOM-Tool-Portable\"
copy "next.config.js" "BOM-Tool-Portable\"
copy "tailwind.config.js" "BOM-Tool-Portable\"
copy "postcss.config.js" "BOM-Tool-Portable\"
copy "tsconfig.json" "BOM-Tool-Portable\"
copy "excel_tool.py" "BOM-Tool-Portable\"
copy "deploy.bat" "BOM-Tool-Portable\"
copy "DEPLOYMENT.md" "BOM-Tool-Portable\"

REM Create README for portable version
echo 📖 Creating instructions...
(
echo # BOM Comparison Tool - Portable Version
echo.
echo ## Quick Start
echo 1. Install Docker Desktop
echo 2. Run deploy.bat
echo 3. Open http://localhost in your browser
echo.
echo ## System Requirements
echo - Windows 10/11
echo - Docker Desktop
echo - 4GB RAM available
echo.
echo ## Installation
echo 1. Extract this folder anywhere on your computer
echo 2. Double-click deploy.bat
echo 3. Wait for "Deployment complete!" message
echo 4. Use the tool at http://localhost
echo.
echo ## For IT Departments
echo - All data stays local on the user's machine
echo - No internet connection required after initial Docker image download
echo - Portable - can be copied to multiple computers
echo - No admin rights required ^(except for Docker Desktop installation^)
) > "BOM-Tool-Portable\README.txt"

echo.
echo ✅ Portable version created in 'BOM-Tool-Portable' folder
echo.
echo 📋 To distribute:
echo   1. Zip the 'BOM-Tool-Portable' folder
echo   2. Send to employees
echo   3. They extract and run deploy.bat
echo.
echo 💡 Each user will need Docker Desktop installed 
pause