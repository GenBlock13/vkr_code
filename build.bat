@echo off
chcp 65001 >nul
echo ============================================================
echo  ReviewGuard — сборка исполняемого файла (PyInstaller)
echo ============================================================
echo.

REM Проверяем, что виртуальное окружение активировано или pip доступен
where python >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Python не найден. Активируйте venv или установите Python.
    pause
    exit /b 1
)

echo [1/3] Установка PyInstaller...
pip install pyinstaller --quiet
if errorlevel 1 (
    echo [ОШИБКА] Не удалось установить PyInstaller.
    pause
    exit /b 1
)

echo [2/3] Сборка приложения...
echo       (занимает 1–3 минуты, пожалуйста, подождите)
echo.

pyinstaller ^
    --noconfirm ^
    --name "ReviewGuard" ^
    --onedir ^
    --windowed ^
    --add-data "app.py;." ^
    --add-data "bot_detector.py;." ^
    --add-data "utils.py;." ^
    --add-data "marketplace_loader.py;." ^
    --add-data "demo_data;demo_data" ^
    --add-data ".streamlit;.streamlit" ^
    --collect-all streamlit ^
    --collect-all plotly ^
    --collect-all sklearn ^
    --collect-all altair ^
    --collect-all pydeck ^
    --hidden-import "sklearn.ensemble._forest" ^
    --hidden-import "sklearn.feature_extraction.text" ^
    --hidden-import "sklearn.pipeline" ^
    --hidden-import "sklearn.metrics" ^
    --hidden-import "sklearn.model_selection" ^
    --hidden-import "joblib" ^
    --hidden-import "pandas" ^
    --hidden-import "numpy" ^
    --hidden-import "requests" ^
    --hidden-import "bs4" ^
    launcher.py

if errorlevel 1 (
    echo.
    echo [ОШИБКА] Сборка не удалась. Проверьте вывод PyInstaller выше.
    pause
    exit /b 1
)

echo.
echo [3/3] Копирование дополнительных файлов...

REM Копируем .streamlit в папку рядом с EXE (Streamlit ищет его там же)
if exist "dist\ReviewGuard\_internal\.streamlit" (
    xcopy ".streamlit" "dist\ReviewGuard\.streamlit\" /E /Y /Q
)

echo.
echo ============================================================
echo  ГОТОВО!
echo ============================================================
echo  Папка: dist\ReviewGuard\
echo  Запуск: dist\ReviewGuard\ReviewGuard.exe
echo.
echo  Для переноса на флешку скопируйте папку dist\ReviewGuard\
echo  целиком — запускайте ReviewGuard.exe с любого компьютера.
echo ============================================================
echo.
pause
