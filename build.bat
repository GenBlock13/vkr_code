@echo off
chcp 65001 >nul
echo.
echo ============================================================
echo  ReviewGuard — сборка портативного EXE (PyInstaller)
echo  Запускайте из корневой папки проекта.
echo ============================================================
echo.

:: ── 1. Проверка Python ───────────────────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Python не найден в PATH.
    echo          Скачайте Python 3.10+ с https://www.python.org и установите,
    echo          поставив галочку "Add Python to PATH".
    pause
    exit /b 1
)

:: Проверяем версию Python (нужна 3.10+)
python -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Требуется Python 3.10 или новее.
    python --version
    pause
    exit /b 1
)

python --version

:: ── 2. Виртуальное окружение ─────────────────────────────────────────────────
if not exist ".venv\" (
    echo.
    echo [1/4] Создание виртуального окружения .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось создать venv.
        pause
        exit /b 1
    )
) else (
    echo [1/4] Виртуальное окружение .venv уже существует, пропускаем.
)

:: ── 3. Установка зависимостей ────────────────────────────────────────────────
echo.
echo [2/4] Установка зависимостей из requirements.txt...
.venv\Scripts\pip.exe install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ОШИБКА] Не удалось установить зависимости.
    pause
    exit /b 1
)

echo [2/4] Установка PyInstaller...
.venv\Scripts\pip.exe install pyinstaller --quiet
if errorlevel 1 (
    echo [ОШИБКА] Не удалось установить PyInstaller.
    pause
    exit /b 1
)

:: ── 4. Сборка EXE ────────────────────────────────────────────────────────────
echo.
echo [3/4] Сборка приложения...
echo       Это займёт 2–5 минут, пожалуйста, подождите.
echo.

.venv\Scripts\pyinstaller.exe ^
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
    echo [ОШИБКА] Сборка не удалась. Смотрите вывод PyInstaller выше.
    pause
    exit /b 1
)

:: ── 5. Финальные шаги ────────────────────────────────────────────────────────
echo.
echo [4/4] Финальная настройка...

:: Удаляем промежуточный EXE из build\ чтобы не запутаться
if exist "build\ReviewGuard\ReviewGuard.exe" (
    ren "build\ReviewGuard\ReviewGuard.exe" "ReviewGuard_BUILD_NOT_RUN.exe" >nul 2>&1
)

echo.
echo ============================================================
echo  ГОТОВО!
echo ============================================================
echo.
echo  Запуск:   dist\ReviewGuard\ReviewGuard.exe
echo  Размер:   ~350-400 МБ (папка dist\ReviewGuard\ целиком)
echo.
echo  Для переноса на другой компьютер или флеш-накопитель:
echo  скопируйте папку dist\ReviewGuard\ ЦЕЛИКОМ.
echo  Python на целевом ПК не требуется.
echo.
echo  ВАЖНО: не запускайте EXE из папки build\ —
echo  это промежуточный артефакт без библиотек.
echo ============================================================
echo.
pause
