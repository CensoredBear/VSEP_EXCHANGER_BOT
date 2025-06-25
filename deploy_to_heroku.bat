@echo off
echo ========================================
echo VSEP Exchanger Bot - Heroku Deploy
echo ========================================

echo.
echo 1. Добавляем файлы в Git...
git add .

echo.
echo 2. Создаем коммит...
git commit -m "Deploy to Heroku"

echo.
echo 3. Отправляем на Heroku...
git push heroku main

echo.
echo ========================================
echo Деплой завершен!
echo ========================================
echo.
echo Для просмотра логов используйте:
echo heroku logs --tail
echo.
echo Для открытия приложения:
echo heroku open
echo.
pause 