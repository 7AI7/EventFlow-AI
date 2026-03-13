@echo off
set PHONE=+919876543299
set MESSAGE=hi, tell me about the events
set BASE_URL=http://localhost:5678
set WEBHOOK_PATH=/webhook/chat-local

echo Sending request to: %BASE_URL%%WEBHOOK_PATH%
echo Phone: %PHONE%
echo Message: %MESSAGE%
echo.

curl -X POST "%BASE_URL%%WEBHOOK_PATH%" ^
  -H "Content-Type: application/json" ^
  -d "{\"phone\":\"%PHONE%\",\"message\":\"%MESSAGE%\"}"

echo.
echo HTTP Status: %ERRORLEVEL%
