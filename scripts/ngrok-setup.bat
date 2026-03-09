@echo off
echo 🔧 Setting up ngrok for BOM Comparison Tool...
echo.

echo 🔑 Step 1: Adding your auth token...
ngrok config add-authtoken 31THtlOvfItg5OSI2jIuH5dOsnF_2Rh8vohUmKuSmFx59JyyV

echo.
echo ✅ Auth token added successfully!
echo.

echo 🌐 Step 2: Starting tunnel to localhost:80...
echo.
echo ⚠️  IMPORTANT: 
echo    - Keep this window open while employees test
echo    - Your local server is running on localhost:80
echo    - ngrok will create a public tunnel to it
echo.
echo 📧 Copy the https://xxxxx.ngrok.app URL and share with employees
echo.

pause

echo Starting ngrok tunnel...
ngrok http 80