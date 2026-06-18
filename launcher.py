"""
launcher.py — графический лаунчер ReviewGuard.

Запускает обучение модели и веб-интерфейс из одного окна,
без командной строки и установленной Python-среды на целевой машине.

ВКР: Еременко Г.С., ТГУ им. Г.Р. Державина, 2026
"""

import multiprocessing
multiprocessing.freeze_support()   # обязательно до любого GUI/импорта — иначе PyInstaller
                                   # порождает новые окна для каждого worker-процесса

import os
import sys

# ── Режим субпроцесса Streamlit ───────────────────────────────────────────────
# Streamlit нельзя запускать из фонового потока — он устанавливает
# signal-обработчики, доступные только в главном потоке.
# Решение: лаунчер перезапускает сам себя с флагом --run-streamlit;
# дочерний процесс запускает Streamlit прямо из главного потока.
if len(sys.argv) >= 3 and sys.argv[1] == "--run-streamlit":
    _app_path = sys.argv[2]
    _port = int(sys.argv[3]) if len(sys.argv) > 3 else 8501

    def _st_base() -> str:
        if getattr(sys, "frozen", False):
            return sys._MEIPASS
        return os.path.dirname(os.path.abspath(__file__))

    _base = _st_base()
    if _base not in sys.path:
        sys.path.insert(0, _base)

    # Env-переменные читаются ДО инициализации конфига — самый надёжный способ.
    import os as _os
    _os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"
    _os.environ["STREAMLIT_SERVER_HEADLESS"]         = "true"
    _os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"

    # Используем CLI-подход: Click разбирает аргументы до любой инициализации
    # конфига, поэтому конфликт dev-mode/port не возникает.
    sys.argv = ["streamlit", "run", _app_path]
    from streamlit.web.cli import main as _st_cli
    _st_cli(prog_name="streamlit")
    sys.exit(0)
# ─────────────────────────────────────────────────────────────────────────────

import subprocess
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import font as tkfont
from tkinter import messagebox, scrolledtext

# ── Корень приложения (работает и как .py, и как .exe от PyInstaller) ─────────

def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return sys._MEIPASS          # PyInstaller извлекает файлы сюда
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = _base_dir()
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# ── Земляная палитра ───────────────────────────────────────────────────────────
C_BG       = "#F7F3EC"   # тёплый крем — основной фон
C_PANEL    = "#EDE8DC"   # чуть темнее — панель
C_TERM_BG  = "#28231E"   # тёмный шоколад — терминал
C_TERM_FG  = "#D4C9B0"   # пергамент — текст терминала
C_ACCENT   = "#7D6B52"   # охра / тёплый коричневый — шапка
C_GOLD     = "#A88420"   # золотая охра — кнопка обучения
C_GREEN    = "#4E7048"   # лесной зелёный — кнопка запуска
C_BORDER   = "#C4B49A"   # светлый тан — рамки
C_TEXT     = "#3A312A"   # тёмно-коричневый — основной текст
C_TEXT2    = "#6B5F54"   # средний коричневый — вторичный текст
C_ERR      = "#904040"   # приглушённый красный
C_OK       = "#4F7A3A"   # приглушённый зелёный
C_INFO     = "#4A7080"   # сине-серый

# ── Информационная панель ──────────────────────────────────────────────────────
INFO_TEXT = """\
ДЕТЕКТОР АНОМАЛЬНЫХ ОТЗЫВОВ
МАРКЕТПЛЕЙСА
ВКР · ТГУ им. Г.Р. Державина
Еременко Г.С. · 2026
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

МЕТОД
TF-IDF char n-grams (2–4) +
Random Forest (200 деревьев)
Датасет: 800 отзывов
  400 подлинных + 400 ботовых
Разбиение: 80/20, stratify

МЕТРИКИ ПОСЛЕДНЕГО ОБУЧЕНИЯ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Accuracy    98.75 %
ROC-AUC     1.0000
OOB score   0.9953
CV F1 macro 0.9950 ± 0.0047
TN=80  FP=0  FN=2  TP=78

СОСТАВ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
app.py            — интерфейс
bot_detector.py   — обучение
utils.py          — признаки
marketplace_loader— источники
demo_data/        — офлайн

ЭТИКА И ОГРАНИЧЕНИЯ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Тайм-аут 10 с, пауза ≥ 1 с
Имена авторов не сохраняются
Метки — оценка по тексту,
не установленный факт накрутки
Generic-парсер: только статич.
HTML (не SPA/JS-рендеринг)
"""


class LauncherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ReviewGuard — Детектор аномальных отзывов")
        self.configure(bg=C_BG)
        self.geometry("980x700")
        self.minsize(820, 580)
        self._streamlit_started = False
        self._streamlit_port = 8501
        self._streamlit_proc = None

        self._build_ui()
        self.after(200, self._startup_check)

    # ── Построение UI ─────────────────────────────────────────────────────────

    def _build_ui(self):
        mono   = tkfont.Font(family="Consolas",  size=9)
        ui     = tkfont.Font(family="Segoe UI",  size=9)
        ui_b   = tkfont.Font(family="Segoe UI",  size=9,  weight="bold")
        title  = tkfont.Font(family="Segoe UI",  size=10, weight="bold")
        hdr_f  = tkfont.Font(family="Segoe UI",  size=13, weight="bold")
        btn_f  = tkfont.Font(family="Segoe UI",  size=10, weight="bold")

        # ── Шапка ─────────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=C_ACCENT, pady=11)
        hdr.pack(fill="x")
        tk.Label(hdr, text="ReviewGuard",
                 bg=C_ACCENT, fg="white", font=hdr_f).pack(side="left", padx=16)
        tk.Label(hdr, text="Детектор аномальных отзывов маркетплейса",
                 bg=C_ACCENT, fg="#D9CFC4", font=ui).pack(side="left", padx=2)

        # ── Основная область ──────────────────────────────────────────────────
        main = tk.Frame(self, bg=C_BG)
        main.pack(fill="both", expand=True, padx=12, pady=10)

        # Левая панель — инфо
        left = tk.Frame(main, bg=C_PANEL,
                        highlightbackground=C_BORDER, highlightthickness=1)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.configure(width=230)
        left.pack_propagate(False)

        tk.Label(left, text="Техническая информация",
                 bg=C_PANEL, fg=C_TEXT, font=title
                 ).pack(anchor="w", padx=10, pady=(8, 0))

        info_t = tk.Text(left, bg=C_PANEL, fg=C_TEXT2, font=mono,
                         wrap="word", bd=0, relief="flat",
                         state="normal", cursor="arrow", selectbackground=C_BORDER)
        info_t.insert("1.0", INFO_TEXT)
        info_t.configure(state="disabled")
        sb = tk.Scrollbar(left, command=info_t.yview, bg=C_PANEL,
                          troughcolor=C_PANEL, width=10)
        info_t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", pady=(0, 8))
        info_t.pack(fill="both", expand=True, padx=(8, 0), pady=(4, 8))

        # Правая панель — терминал
        right = tk.Frame(main, bg=C_BG)
        right.pack(side="left", fill="both", expand=True)

        tk.Label(right, text="Вывод терминала",
                 bg=C_BG, fg=C_TEXT, font=title).pack(anchor="w", pady=(0, 4))

        self.terminal = scrolledtext.ScrolledText(
            right, bg=C_TERM_BG, fg=C_TERM_FG, font=mono,
            wrap="word", bd=0, insertbackground=C_TERM_FG,
            state="disabled", selectbackground="#5A5045"
        )
        self.terminal.pack(fill="both", expand=True)
        self.terminal.tag_configure("ok",   foreground="#7CB86A")
        self.terminal.tag_configure("err",  foreground="#C47070")
        self.terminal.tag_configure("head", foreground="#C8A040")
        self.terminal.tag_configure("info", foreground="#6AAABB")
        self.terminal.tag_configure("dim",  foreground="#7A6F64")

        # ── Панель кнопок ─────────────────────────────────────────────────────
        btn_bar = tk.Frame(self, bg=C_BG, pady=10)
        btn_bar.pack(fill="x", padx=12)

        self.btn_train = tk.Button(
            btn_bar, text="⚙  Обучить модель",
            bg=C_GOLD, fg="white", activebackground="#7A6010",
            activeforeground="white", font=btn_f,
            relief="flat", padx=20, pady=9, cursor="hand2",
            command=self._on_train
        )
        self.btn_train.pack(side="left", padx=(0, 8))

        self.btn_web = tk.Button(
            btn_bar, text="🌐  Открыть веб-интерфейс",
            bg=C_GREEN, fg="white", activebackground="#2E5028",
            activeforeground="white", font=btn_f,
            relief="flat", padx=20, pady=9, cursor="hand2",
            command=self._on_launch
        )
        self.btn_web.pack(side="left", padx=(0, 8))

        tk.Button(
            btn_bar, text="Выход",
            bg=C_PANEL, fg=C_TEXT2, activebackground=C_BORDER,
            font=ui, relief="flat", padx=14, pady=9, cursor="hand2",
            command=self._on_exit
        ).pack(side="right")

        # Кнопка очистки терминала
        tk.Button(
            btn_bar, text="Очистить",
            bg=C_PANEL, fg=C_TEXT2, activebackground=C_BORDER,
            font=ui, relief="flat", padx=10, pady=9, cursor="hand2",
            command=self._clear_terminal
        ).pack(side="right", padx=(0, 6))

        # ── Статус-строка ──────────────────────────────────────────────────────
        self.status_var = tk.StringVar(value="Инициализация…")
        tk.Label(self, textvariable=self.status_var,
                 bg=C_PANEL, fg=C_TEXT2, font=ui,
                 anchor="w", padx=12, pady=5
                 ).pack(fill="x", side="bottom")

    # ── Запуск: проверка модели ────────────────────────────────────────────────

    def _startup_check(self):
        model_path = os.path.join(BASE_DIR, "model_pipeline.pkl")
        if os.path.exists(model_path):
            self._log("✓ Модель найдена и готова к использованию.\n", "ok")
            self._log("  Нажмите «Открыть веб-интерфейс» для запуска анализатора.\n", "dim")
            self._status("✓ Модель готова")
        else:
            self._log("Модель не найдена.\n", "err")
            self._log("Для работы системы требуется обучение.\n", "info")
            self._log("Нажмите «Обучить модель» — это займёт около 10–20 секунд.\n\n", "dim")
            self._status("⚠  Модель не обучена — нажмите «Обучить модель»")
            if messagebox.askyesno(
                "ReviewGuard",
                "Обученная модель не найдена.\n\nЗапустить обучение сейчас?",
                icon="question"
            ):
                self._on_train()

    # ── Обучение модели ────────────────────────────────────────────────────────

    def _on_train(self):
        self.btn_train.configure(state="disabled", text="⚙  Обучение…")
        self._status("Обучение модели…")
        threading.Thread(target=self._train_worker, daemon=True).start()

    def _train_worker(self):
        self._log("\n" + "═" * 55 + "\n", "head")
        self._log("  ЗАПУСК ОБУЧЕНИЯ МОДЕЛИ\n", "head")
        self._log("═" * 55 + "\n", "head")
        try:
            import io as _io
            import importlib

            # Импортируем и перезагружаем, чтобы повторный запуск тоже работал
            import bot_detector
            importlib.reload(bot_detector)

            # Перехватываем stdout bot_detector.main()
            old_stdout = sys.stdout
            buf = _io.StringIO()
            sys.stdout = buf
            try:
                bot_detector.main()
            finally:
                sys.stdout = old_stdout

            output = buf.getvalue()
            for line in output.splitlines(keepends=True):
                if line.startswith("✓"):
                    tag = "ok"
                elif line.startswith("=") or line.startswith("ДАТАСЕТ") or line.startswith("РЕЗУЛЬТАТЫ"):
                    tag = "head"
                elif line.strip() == "":
                    tag = None
                else:
                    tag = None
                self._log(line, tag)

            self._log("\n✓ Обучение завершено. Веб-интерфейс готов к запуску.\n", "ok")
            self._status("✓ Модель обучена и сохранена")
            self.after(0, lambda: self.btn_train.configure(
                state="normal", text="⚙  Переобучить модель"))
        except Exception as exc:
            self._log(f"\n✗ Ошибка обучения: {exc}\n", "err")
            self._status(f"Ошибка: {exc}")
            self.after(0, lambda: self.btn_train.configure(
                state="normal", text="⚙  Обучить модель"))

    # ── Запуск веб-интерфейса ─────────────────────────────────────────────────

    def _on_launch(self):
        if self._streamlit_started:
            webbrowser.open(f"http://localhost:{self._streamlit_port}")
            self._log("🌐 Открываю вкладку браузера…\n", "info")
            return

        model_path = os.path.join(BASE_DIR, "model_pipeline.pkl")
        if not os.path.exists(model_path):
            messagebox.showwarning(
                "Модель не найдена",
                "Сначала обучите модель (кнопка «Обучить модель»)."
            )
            return

        self._streamlit_started = True
        self.btn_web.configure(state="disabled", text="🌐  Запуск сервера…")
        self._status("Запуск Streamlit-сервера…")
        threading.Thread(target=self._streamlit_worker, daemon=True).start()

    def _streamlit_worker(self):
        try:
            app_path = os.path.join(BASE_DIR, "app.py")
            self._log("\n🌐 Запуск Streamlit (http://localhost:8501)…\n", "info")

            # Streamlit запускается как дочерний процесс самого себя (--run-streamlit).
            # stdout/stderr перехватываются и выводятся в терминал лаунчера.
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc = subprocess.Popen(
                [sys.executable, "--run-streamlit", app_path,
                 str(self._streamlit_port)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=flags,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self._streamlit_proc = proc

            # Стримим вывод подпроцесса в терминал
            def _read_output():
                for line in proc.stdout:
                    self._log(line.rstrip("\n") + "\n", "dim")

            threading.Thread(target=_read_output, daemon=True).start()

            # Открыть браузер после паузы (ждём пока сервер поднимется)
            def _open():
                time.sleep(4.0)
                if proc.poll() is None:
                    webbrowser.open(f"http://localhost:{self._streamlit_port}")
                    self._log("✓ Браузер открыт.\n", "ok")
                    self._status(f"✓ Работает: http://localhost:{self._streamlit_port}")
                    self.after(0, lambda: self.btn_web.configure(
                        state="normal", text="🌐  Открыть вкладку браузера"))
                else:
                    self._log("✗ Сервер завершился раньше времени. "
                              "Смотрите вывод выше.\n", "err")
                    self._status("Ошибка запуска сервера")
                    self._streamlit_started = False
                    self.after(0, lambda: self.btn_web.configure(
                        state="normal", text="🌐  Открыть веб-интерфейс"))

            threading.Thread(target=_open, daemon=True).start()
            proc.wait()

        except Exception as exc:
            self._log(f"\n✗ Ошибка запуска: {exc}\n", "err")
            self._status(f"Ошибка: {exc}")
            self._streamlit_started = False
            self.after(0, lambda: self.btn_web.configure(
                state="normal", text="🌐  Открыть веб-интерфейс"))

    # ── Утилиты ───────────────────────────────────────────────────────────────

    def _log(self, text: str, tag: str | None = None):
        def _do():
            self.terminal.configure(state="normal")
            self.terminal.insert("end", text, (tag,) if tag else ())
            self.terminal.see("end")
            self.terminal.configure(state="disabled")
        self.after(0, _do)

    def _status(self, text: str):
        self.after(0, lambda: self.status_var.set(text))

    def _clear_terminal(self):
        self.terminal.configure(state="normal")
        self.terminal.delete("1.0", "end")
        self.terminal.configure(state="disabled")

    def _on_exit(self):
        if self._streamlit_proc and self._streamlit_proc.poll() is None:
            self._streamlit_proc.terminate()
        self.destroy()


# ── Точка входа ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = LauncherApp()
    app.mainloop()
