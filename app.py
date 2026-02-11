# manager_app.py
# -*- coding: utf-8 -*-

import os
import sys
import threading
import queue
import shutil
import uuid
from typing import Optional, Dict, Any
import subprocess

import tkinter as tk
from tkinter import ttk

import requests
# manager_app.py
# Отправляет заявки на server.py
# pip install requests

import requests
import os
import json

class AutoScrollbar(ttk.Scrollbar):
    """Scrollbar, который показывается только когда нужен (lo>0 или hi<1). Работает через grid()."""

    def set(self, lo, hi):
        lo = float(lo)
        hi = float(hi)
        if lo <= 0.0 and hi >= 1.0:
            self.grid_remove()
        else:
            self.grid()
        super().set(lo, hi)

    # Запрещаем pack/place, чтобы случайно не сломать автоскрытие
    def pack(self, *args, **kwargs):
        raise tk.TclError("Use grid() with AutoScrollbar")

    def place(self, *args, **kwargs):
        raise tk.TclError("Use grid() with AutoScrollbar")

# ===== Login UI assets (put your file paths here) =====
LOGIN_ICON_PATH = r"Theresa.ico"             # <-- сюда путь к .ico (Windows)
LOGIN_BG_PATH = r"login_background.png"      # <-- сюда путь к .png/.gif (ВАЖНО: PhotoImage НЕ читает .jpg без PIL)

API_URL = os.getenv("API_URL", "http://34.179.169.197")
HTTP_TIMEOUT = 6

# ================== THEME ==================
BG_MAIN = "#1e1e1e"
BG_PANEL = "#252526"
FG_TEXT = "#ffffff"
ACCENT = "#2a82da"

ENTRY_BG = "#333333"
ENTRY_FG = "#ffffff"
PLACEHOLDER_FG = "grey"

CHECKED = "☑"
UNCHECKED = "☐"

# ===== Global font (applies to whole app) =====
APP_FONT_FAMILY = os.getenv("APP_FONT_FAMILY", "Segoe UI")
APP_FONT_SIZE = int(os.getenv("APP_FONT_SIZE", "10"))
APP_FONT = (APP_FONT_FAMILY, APP_FONT_SIZE)
APP_FONT_BOLD = (APP_FONT_FAMILY, APP_FONT_SIZE, "bold")


def get_device_id() -> str:
    return str(uuid.getnode())


def safe_json(resp: requests.Response) -> Dict[str, Any]:
    try:
        j = resp.json()
        return j if isinstance(j, dict) else {"data": j}
    except Exception:
        return {}





def load_login_image(path: str):
    """
    Пытаемся загрузить фон/иконку для окна логина.
    1) PIL (если установлен) — поддерживает png/jpg
    2) tk.PhotoImage — поддерживает png/gif (jpg без PIL не умеет)
    """
    if not path or not os.path.exists(path):
        return None
    try:
        from PIL import Image, ImageTk  # type: ignore
        img = Image.open(path)
        return ImageTk.PhotoImage(img)
    except Exception:
        pass
    try:
        return tk.PhotoImage(file=path)
    except Exception:
        return None


def disable_tk_bell(widget: tk.Misc) -> None:
    """Полностью отключает системный 'ding' Tk/Tcl (команда bell)."""
    try:
        tk_ = widget.tk
        try:
            existing = tk_.call("info", "commands", "__bell_orig")
            if existing:
                return
        except Exception:
            pass

        try:
            tk_.call("rename", "bell", "__bell_orig")
        except Exception:
            pass

        tk_.createcommand("bell", lambda *args: None)
    except Exception:
        pass


def apply_global_font(root: tk.Tk) -> None:
    """
    1) option_add влияет на Tk-виджеты (Label, Button, Entry и т.д.)
    2) ttk требует Style.configure отдельно (см. init_styles)
    """
    try:
        root.option_add("*Font", APP_FONT)
    except Exception:
        pass


def app_base_dir() -> str:
    """Папка запуска: рядом с .exe (PyInstaller) или рядом со скриптом."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


# ================== Dark dialogs (instead of messagebox) ==================
def _set_window_icon(win: tk.Toplevel) -> None:
    try:
        if LOGIN_ICON_PATH and os.path.exists(LOGIN_ICON_PATH):
            win.iconbitmap(LOGIN_ICON_PATH)
    except Exception:
        pass


def dark_message(parent: tk.Misc, title: str, text: str, kind: str = "info") -> None:
    """
    kind: info | warning | error
    Окно автоматически подстраивается под размер текста.
    """
    win = tk.Toplevel(parent)
    win.title(title)
    _set_window_icon(win)
    win.configure(bg=BG_MAIN)

    # Модальное поведение
    win.transient(parent.winfo_toplevel())
    win.grab_set()
    disable_tk_bell(win)

    # --- ТЕЛО ---
    body = tk.Frame(win, bg=BG_MAIN)
    body.pack(fill="both", expand=True, padx=16, pady=16)

    # Ограничиваем ширину текста, чтобы не получались "очень широкие" окна.
    # Можно подогнать значения под себя.
    win.update_idletasks()
    screen_w = win.winfo_screenwidth()
    screen_h = win.winfo_screenheight()

    max_text_w = min(720, int(screen_w * 0.70))   # максимум ширины текста
    min_win_w  = 360                              # минимум ширины окна
    min_win_h  = 160                              # минимум высоты окна

    msg = tk.Label(
        body,
        text=text,
        bg=BG_MAIN,
        fg=FG_TEXT,
        justify="left",
        anchor="nw",
        wraplength=max_text_w,
    )
    msg.pack(fill="both", expand=True)

    # --- НИЗ С КНОПКОЙ ---
    footer = tk.Frame(win, bg=BG_MAIN)
    footer.pack(fill="x", padx=16, pady=(0, 16))

    def close():
        try:
            win.grab_release()
        except Exception:
            pass
        win.destroy()

    ok_btn = tk.Button(
        footer,
        text="OK",
        command=close,
        bg=ACCENT,
        fg="white",
        activebackground=ACCENT,
        activeforeground="white",
        bd=0,
        padx=18,
        pady=8,
    )
    ok_btn.pack(side="right")

    # Enter/Esc
    win.bind("<Return>", lambda _e: close())
    win.bind("<Escape>", lambda _e: close())
    ok_btn.focus_set()

    # --- АВТОРАЗМЕР ---
    win.update_idletasks()
    req_w = max(min_win_w, win.winfo_reqwidth())
    req_h = max(min_win_h, win.winfo_reqheight())

    # Ограничения, чтобы окно не занимало пол-экрана на больших текстах
    max_win_w = int(screen_w * 0.85)
    max_win_h = int(screen_h * 0.85)
    req_w = min(req_w, max_win_w)
    req_h = min(req_h, max_win_h)

    win.geometry(f"{req_w}x{req_h}")

    # Центрируем относительно родителя
    win.update_idletasks()
    try:
        parent_win = parent.winfo_toplevel()
        px = parent_win.winfo_rootx()
        py = parent_win.winfo_rooty()
        pw = parent_win.winfo_width()
        ph = parent_win.winfo_height()
        x = px + max(0, (pw - req_w) // 2)
        y = py + max(0, (ph - req_h) // 2)
        win.geometry(f"{req_w}x{req_h}+{x}+{y}")
    except Exception:
        # запасной вариант по центру экрана
        x = (screen_w - req_w) // 2
        y = (screen_h - req_h) // 2
        win.geometry(f"{req_w}x{req_h}+{x}+{y}")

    parent.winfo_toplevel().wait_window(win)

def dark_error(parent: tk.Misc, title: str, message: str) -> None:
    win = tk.Toplevel(parent)
    win.withdraw()
    win.overrideredirect(True)
    win.configure(bg="#0f0f0f")
    disable_tk_bell(win)

    win.transient(parent.winfo_toplevel())
    win.grab_set()

    W, H = 560, 240
    win.update_idletasks()
    x = (win.winfo_screenwidth() - W) // 2
    y = (win.winfo_screenheight() - H) // 2
    win.geometry(f"{W}x{H}+{x}+{y}")

    border = tk.Frame(win, bg="#ff3b30")  # красная рамка
    border.pack(fill="both", expand=True)

    body = tk.Frame(border, bg="#1b1b1b", padx=14, pady=12)
    body.pack(fill="both", expand=True, padx=2, pady=2)

    # заголовок
    header = tk.Frame(body, bg="#1b1b1b", height=34)
    header.pack(fill="x")
    header.pack_propagate(False)

    tk.Label(header, text=f"⛔ {title}", bg="#1b1b1b", fg="white", font=APP_FONT_BOLD).pack(side="left")

    def start_move(event):
        win.x = event.x
        win.y = event.y

    def stop_move(event):
        win.x = None
        win.y = None

    def do_move(event):
        deltax = event.x - win.x
        deltay = event.y - win.y
        x = win.winfo_x() + deltax
        y = win.winfo_y() + deltay
        win.geometry(f"+{x}+{y}")

    header.bind("<ButtonPress-1>", start_move)
    header.bind("<B1-Motion>", do_move)

    def close():
        try:
            win.grab_release()
        except Exception:
            pass
        win.destroy()

    tk.Button(
        header, text="✕", command=close,
        bg="#1b1b1b", fg="white", bd=0,
        activebackground="#2a2a2a", activeforeground="white",
        font=APP_FONT_BOLD
    ).pack(side="right")

    # текст
    msg = tk.Label(body, text=message, bg="#1b1b1b", fg="white",
                   font=APP_FONT, justify="left", anchor="nw", wraplength=W-120)
    msg.pack(fill="both", expand=True, pady=(12, 10))

    # кнопка
    tk.Button(body, text="OK", command=close, bg="#ff3b30", fg="white",
              bd=0, padx=18, pady=8, font=APP_FONT_BOLD).pack(anchor="e")

    win.bind("<Escape>", lambda _e: close())
    win.bind("<Return>", lambda _e: close())

    win.deiconify()
    win.lift()
    win.wait_window(win)

def error(parent: tk.Misc, title: str, message: str) -> None:
    dark_error(parent, title, message)

def info(parent: tk.Misc, title: str, text: str) -> None:
    dark_message(parent, title, text, "info")


def warn(parent: tk.Misc, title: str, text: str) -> None:
    dark_message(parent, title, text, "warning")


def error(parent: tk.Misc, title: str, text: str) -> None:
    dark_message(parent, title, text, "error")



def exit_app(parent: tk.Misc, message: str = "Ключ продукта недействителен") -> None:
    """Показывает окно ошибки и завершает программу."""
    try:
        error(parent, "Ошибка", message)
    finally:
        try:
            parent.winfo_toplevel().destroy()
        except Exception:
            pass
        try:
            import os
            os._exit(0)
        except Exception:
            raise SystemExit(0)


class AppGUI:
    def __init__(self, root, token: str):
        self.root = root
        apply_global_font(self.root)
        disable_tk_bell(self.root)

        self.token = token
        self.headers = {"Authorization": f"Bearer {token}"}

        self.ui_queue = queue.Queue()
        self.root.after(50, self._process_ui_queue)

        self.http = requests.Session()
        self.http.headers.update(self.headers)
        # License is checked only on login/registration (server-authoritative).

        self.active_orders = set()
        self.offers_seen = {}
        self.removed_offers = {}
        self.polling_active = False
        self.temp_id_counter = -1

        root.title("Логистика — заявки (Manager)")
        root.geometry("1700x880")
        root.configure(bg=BG_MAIN)

        # Иконка главного окна
        try:
            if LOGIN_ICON_PATH and os.path.exists(LOGIN_ICON_PATH):
                root.iconbitmap(LOGIN_ICON_PATH)
        except Exception:
            pass

        self.init_styles()
        self.build_left_panel()
        self.build_top_buttons()
        self.build_center_panel()
        self.build_offers_panel()

        # Горячие клавиши:
        # ESC — отменить/сбросить ввод
        # Enter в полях слева — добавить заявку
        # Ctrl+Enter — добавить заявку (глобально)
        self.root.bind("<Escape>", self.on_escape, add="+")
        self.root.bind("<Control-Return>", lambda _e: self.add_order(), add="+")
        self.root.bind("<Control-KP_Enter>", lambda _e: self.add_order(), add="+")

        self.refresh_orders(initial_fetch=True)

    def _process_ui_queue(self):
        try:
            while True:
                fn = self.ui_queue.get_nowait()
                try:
                    fn()
                except Exception as e:
                    print("UI callback error:", e)
        except queue.Empty:
            pass
        self.root.after(50, self._process_ui_queue)

    def run_http_async(self, work_fn, on_ok=None, on_err=None):
        def _runner():
            try:
                result = work_fn()
                if on_ok:
                    self.ui_queue.put(lambda: on_ok(result))
            except Exception as e:
                if on_err:
                    self.ui_queue.put(lambda: on_err(e))
                else:
                    self.ui_queue.put(lambda: error(self.root, "Ошибка", str(e)))

        threading.Thread(target=_runner, daemon=True).start()

    def init_styles(self):
        style = ttk.Style(self.root)
        style.theme_use("default")

        # Базовые ttk-шрифты/цвета
        style.configure(".", font=APP_FONT)
        style.configure("TLabel", background=BG_PANEL, foreground=FG_TEXT, font=APP_FONT)
        style.configure("TFrame", background=BG_MAIN)
        style.configure("TButton", font=APP_FONT)

        style.configure(
            "Dark.Treeview",
            background=BG_MAIN,
            foreground=FG_TEXT,
            fieldbackground=BG_MAIN,
            rowheight=30,
            borderwidth=0,
            font=APP_FONT,
        )
        style.map(
            "Dark.Treeview",
            background=[("selected", ACCENT)],
            foreground=[("selected", "white")],
        )
        style.configure(
            "Dark.Treeview.Heading",
            background=BG_PANEL,
            foreground=FG_TEXT,
            relief="flat",
            font=APP_FONT_BOLD,
        )

    def init_styles(self):
        style = ttk.Style(self.root)
        style.theme_use("default")

        style.configure(
            "Dark.Treeview",
            background=BG_MAIN,
            foreground=FG_TEXT,
            fieldbackground=BG_MAIN,
            rowheight=30,
            borderwidth=0,
        )
        style.map(
            "Dark.Treeview",
            background=[("selected", ACCENT)],
            foreground=[("selected", "white")],
        )
        style.configure("Dark.Treeview.Heading", background=BG_PANEL, foreground=FG_TEXT, relief="flat")

        # --- thin scrollbars (визуально "без фона") ---
        style.configure(
            "Thin.Vertical.TScrollbar",
            gripcount=0,
            borderwidth=0,
            relief="flat",
            troughcolor=BG_MAIN,  # фон = фон таблицы
            background=BG_PANEL,  # бегунок
            darkcolor=BG_PANEL,
            lightcolor=BG_PANEL,
            arrowcolor=BG_MAIN,  # стрелки "прячем" в фон
            width=9,
        )
        style.configure(
            "Thin.Horizontal.TScrollbar",
            gripcount=0,
            borderwidth=0,
            relief="flat",
            troughcolor=BG_MAIN,
            background=BG_PANEL,
            darkcolor=BG_PANEL,
            lightcolor=BG_PANEL,
            arrowcolor=BG_MAIN,
            width=9,
        )

        # Убираем стрелки/рамки (чтобы было ближе к твоему примеру)
        style.layout("Thin.Vertical.TScrollbar", [
            ("Vertical.Scrollbar.trough", {"children": [
                ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})
            ], "sticky": "ns"})
        ])
        style.layout("Thin.Horizontal.TScrollbar", [
            ("Horizontal.Scrollbar.trough", {"children": [
                ("Horizontal.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})
            ], "sticky": "we"})
        ])

    # ===================== PLACEHOLDERS (fixed) =====================
    def _ph_is_active(self, entry: tk.Entry) -> bool:
        return bool(getattr(entry, "_ph_active", False))

    def _ph_text(self, entry: tk.Entry) -> str:
        return str(getattr(entry, "_ph_text", ""))

    def _ph_set(self, entry: tk.Entry, text: str) -> None:
        """Поставить placeholder так, чтобы он НЕ считался введённым текстом."""
        entry._ph_text = text
        entry._ph_active = True
        entry.delete(0, tk.END)
        entry.insert(0, text)
        entry.config(fg=PLACEHOLDER_FG)

    def _ph_clear(self, entry: tk.Entry) -> None:
        """Очистить placeholder (если активен)."""
        if self._ph_is_active(entry):
            entry._ph_active = False
            entry.delete(0, tk.END)
            entry.config(fg=ENTRY_FG)

    def get_entry_value(self, entry: tk.Entry) -> str:
        if self._ph_is_active(entry):
            return ""
        return entry.get().strip()

    def add_placeholder(self, entry: tk.Entry, text: str) -> None:
        self._ph_set(entry, text)

        def on_focus_in(_event):
            self._ph_clear(entry)

        def on_focus_out(_event):
            if not entry.get().strip():
                self._ph_set(entry, self._ph_text(entry))

        entry.bind("<Button-1>", on_focus_in, add="+")
        entry.bind("<FocusIn>", on_focus_in, add="+")
        entry.bind("<FocusOut>", on_focus_out, add="+")

    def reset_left_fields(self) -> None:
        for label, entry in self.entries.items():
            ph = self.entry_placeholders.get(label, "")
            if ph:
                self._ph_set(entry, ph)
            else:
                entry.delete(0, tk.END)
                entry.config(fg=ENTRY_FG)

    def on_escape(self, _event=None):
        try:
            self.reset_left_fields()
        except Exception:
            pass
        try:
            self.tree.selection_remove(self.tree.selection())
        except Exception:
            pass
        try:
            self.offers.selection_remove(self.offers.selection())
        except Exception:
            pass
        return "break"

    def build_left_panel(self):
        left = tk.Frame(self.root, bg=BG_PANEL, padx=12, pady=12)
        left.pack(side="left", fill="y")

        fields = [
            ("Направление", "Откуда - Куда"),
            ("Груз", "Введите груз"),
            ("Тоннаж", "Введите тоннаж"),
            ("Тип транспорта", "Введите тип транспорта"),
            ("Дата", "ДД.ММ.ГГГГ"),
            ("Цена", "Введите цену"),
            ("Требования", "АДР/РЕЖИМ/ПОРТ"),
        ]

        self.entries = {}
        self.entry_placeholders = {}
        for label, placeholder in fields:
            tk.Label(left, text=label, bg=BG_PANEL, fg=FG_TEXT).pack(anchor="w")
            e = tk.Entry(left, bg=ENTRY_BG, fg=ENTRY_FG, width=35, insertbackground="white")
            e.pack(pady=4)
            self.entries[label] = e
            self.entry_placeholders[label] = placeholder
            self.add_placeholder(e, placeholder)
            e.bind("<Return>", lambda _e: self.add_order(), add="+")
            e.bind("<KP_Enter>", lambda _e: self.add_order(), add="+")

    def build_top_buttons(self):
        top = tk.Frame(self.root, bg=BG_MAIN)
        top.pack(fill="x", padx=10, pady=6)

        tk.Button(top, text="➕ Добавить", bg=ACCENT, fg="white", command=self.add_order).pack(
            side="left", padx=5
        )
        tk.Button(top, text="💾 Отправить", bg="#4CAF50", fg="white", command=self.save_and_run).pack(
            side="left", padx=5
        )
        tk.Button(top, text="🗑 Закрыть заявки", bg="#9C27B0", fg="white", command=self.close_selected_orders).pack(
            side="left", padx=5
        )
        tk.Button(top, text="🗑 Удалить отклики", bg="#F44336", fg="white", command=self.delete_selected_offers).pack(
            side="left", padx=5
        )
        tk.Button(top, text="👁 Контакт отклика", bg="#607D8B", fg="white", command=self.open_selected_offer_contact).pack(
            side="left", padx=5
        )
        tk.Button(top, text="🔄 Обновить заявки", bg="#607D8B", fg="white", command=self.refresh_orders).pack(
            side="left", padx=5
        )

    # ================= Orders table =================
    def build_center_panel(self):
        center = tk.Frame(self.root, bg=BG_MAIN)
        center.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        table_wrap = tk.Frame(center, bg=BG_MAIN)
        table_wrap.pack(fill="both", expand=True)

        # grid-сетка, чтобы AutoScrollbar мог скрываться
        table_wrap.grid_rowconfigure(0, weight=1)
        table_wrap.grid_columnconfigure(0, weight=1)

        ybar = AutoScrollbar(table_wrap, orient="vertical", style="Thin.Vertical.TScrollbar")
        xbar = AutoScrollbar(table_wrap, orient="horizontal", style="Thin.Horizontal.TScrollbar")

        self.tree = ttk.Treeview(
            table_wrap,
            style="Dark.Treeview",
            columns=("check", "dir", "cargo", "truck", "price", "info"),
            show="headings",
            selectmode="extended",
            yscrollcommand=ybar.set,
            xscrollcommand=xbar.set,
        )

        self.tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")

        ybar.config(command=self.tree.yview)
        xbar.config(command=self.tree.xview)

        # Заголовки/колонки
        self.tree.heading("check", text="")
        self.tree.column("check", width=40, minwidth=40, stretch=False)

        self.tree.heading("dir", text="Направление")
        self.tree.heading("cargo", text="Груз")
        self.tree.heading("truck", text="Транспорт")
        self.tree.heading("price", text="Цена")
        self.tree.heading("info", text="Требования")

        # фикс ширин (чтобы не "ездили")
        self.tree.column("dir", width=260, minwidth=260, stretch=False)
        self.tree.column("cargo", width=260, minwidth=260, stretch=False)
        self.tree.column("truck", width=180, minwidth=180, stretch=False)
        self.tree.column("price", width=110, minwidth=110, stretch=False)
        self.tree.column("info", width=280, minwidth=280, stretch=False)

        self.tree.bind("<Button-1>", self.on_order_check_click)
        self.id_map = {}

    # ================= Offers table =================
    def build_offers_panel(self):
        right = tk.Frame(self.root, bg=BG_PANEL, padx=10, pady=10)
        right.pack(side="right", fill="y")

        tk.Label(
            right,
            text="Отклики",
            bg=BG_PANEL,
            fg=FG_TEXT,
            font=APP_FONT_BOLD if "APP_FONT_BOLD" in globals() else ("Arial", 12, "bold"),
        ).pack(pady=5)

        table_wrap = tk.Frame(right, bg=BG_PANEL)
        table_wrap.pack(fill="both", expand=True)

        table_wrap.grid_rowconfigure(0, weight=1)
        table_wrap.grid_columnconfigure(0, weight=1)

        ybar = AutoScrollbar(table_wrap, orient="vertical", style="Thin.Vertical.TScrollbar")
        xbar = AutoScrollbar(table_wrap, orient="horizontal", style="Thin.Horizontal.TScrollbar")

        # ✅ ВАЖНО: первая колонка — галочка. Тогда при клике "Компания" не затирается.
        self.offers = ttk.Treeview(
            table_wrap,
            style="Dark.Treeview",
            columns=("check", "company", "price"),
            show="headings",
            height=26,
            yscrollcommand=ybar.set,
            xscrollcommand=xbar.set,
            selectmode="extended",
        )

        self.offers.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")

        ybar.config(command=self.offers.yview)
        xbar.config(command=self.offers.xview)

        # Заголовки
        self.offers.heading("check", text="")
        self.offers.heading("company", text="Компания")
        self.offers.heading("price", text="Цена")

        # Фиксируем ширины (чтобы не "съезжали")
        col_widths = {
            "check": 44,
            "company": 260,
            "price": 120,
        }
        for col, w in col_widths.items():
            self.offers.column(col, width=w, minwidth=w, stretch=False)

        # Клик по первой колонке ставит/снимает галочку
        self.offers.bind("<Button-1>", self.on_offer_click)
        self.offers_map = {}

    def add_order(self):
        try:
            data = {}
            for label, entry in self.entries.items():
                # placeholder никогда не попадает в данные
                data[label] = self.get_entry_value(entry)

            required_fields = {
                "Направление": data["Направление"],
                "Груз": data["Груз"],
                "Тоннаж": data["Тоннаж"],
                "Тип транспорта": data["Тип транспорта"]
            }

            missing = [name for name, value in required_fields.items() if not value]
            if missing:
                error(
                    self.root,
                    "Ошибка",
                    "Заявка не может быть создана.\n\n"
                    "Не заполнены поля:\n• " + "\n• ".join(missing),
                )
                return

            try:
                tonnage = float(data["Тоннаж"])
                if tonnage <= 0:
                    raise ValueError
            except ValueError:
                error(self.root, "Ошибка", "Тоннаж должен быть числом больше")
                return

            try:
                price = float(data["Цена"]) if data["Цена"] else 0.0
            except ValueError:
                error(self.root, "Ошибка", "Цена должна быть числом")
                return

            direction = data["Направление"]
            cargo = data["Груз"]
            truck = data["Тип транспорта"]
            date = data["Дата"]
            info_txt = data["Требования"]

            order_id = self.temp_id_counter
            self.temp_id_counter -= 1

            order = [order_id, direction, cargo, tonnage, truck, date, price, info_txt]
            display_cargo = f"{cargo} {tonnage}т"

            item = self.tree.insert(
                "",
                "end",
                values=(UNCHECKED, direction, display_cargo, truck, f"{price}$" if price else "", info_txt or ""),
            )
            self.id_map[item] = order


            # корректный сброс полей обратно к подсказкам
            self.reset_left_fields()


        except Exception as e:
            error(self.root, "Ошибка", f"Неверный ввод данных заявки\n\n{e}")

    def refresh_orders(self, initial_fetch=False):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.id_map.clear()

        orders = []
        try:
            resp = self.http.get(f"{API_URL}/orders/my", timeout=HTTP_TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                orders = data.get("items") if isinstance(data, dict) else data
                if not isinstance(orders, list):
                    orders = []
                # показываем только заявки со статусом pending (как раньше)
                orders = [o for o in orders if (o.get("status") or "pending") == "pending"]
            elif resp.status_code == 401:
                error(self.root, "Ошибка", "Сессия недействительна. Войдите заново.")
                return
            else:
                j = safe_json(resp)
                error(self.root, "Ошибка", f"Ошибка загрузки заявок")
                return
        except Exception as e:
            error(self.root, "Ошибка", f"Ошибка загрузки заявок: {e}")
            return


        self.active_orders.clear()

        for o in orders:
            oid = o.get("id")
            direction = o.get("direction", "")
            cargo = o.get("cargo", "")
            tonnage = o.get("tonnage", 0) or 0
            truck = o.get("truck", "")
            date = o.get("date", "")
            price = o.get("price", 0) or 0
            info_txt = o.get("info", "")

            display_cargo = f"{cargo} {tonnage}т" if (cargo or tonnage) else ""
            item = self.tree.insert(
                "",
                "end",
                values=(UNCHECKED, direction, display_cargo, truck, f"{price}$" if price else "", info_txt or ""),
            )
            self.id_map[item] = [oid, direction, cargo, tonnage, truck, date, price, info_txt]

            if oid is not None and int(oid) >= 0:
                self.active_orders.add(int(oid))

        if initial_fetch and self.active_orders:
            self.start_polling()

    def on_order_check_click(self, event):
        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if col == "#1" and item:
            values = list(self.tree.item(item, "values"))
            values[0] = CHECKED if values[0] == UNCHECKED else UNCHECKED
            self.tree.item(item, values=values)
            return "break"

    def save_and_run(self):
        if not self.id_map:
            return

        info(self.root, "Публикация", "Заявки загружены. Пожалуйста, ожидайте откликов.")

        for item, order in list(self.id_map.items()):
            order_id = order[0]
            if order_id is None or int(order_id) < 0:
                payload = {
                    "direction": order[1],
                    "cargo": order[2],
                    "tonnage": order[3],
                    "truck": order[4],
                    "date": order[5],
                    "price": order[6],
                    "info": order[7],
                }

                if first:
                    payload["__reset"] = True
                    first = False

                resp = self.http.post(f"{API_URL}/orders/create", json=payload, timeout=10)

                try:
                    resp = self.http.post(f"{API_URL}/orders/create", json=payload, timeout=10)
                    if resp.status_code in (200, 201):
                        new_id = safe_json(resp).get("order_id")
                        if new_id is not None:
                            order[0] = int(new_id)
                            self.active_orders.add(int(new_id))
                            self.id_map[item] = order
                        else:
                            warn(self.root, "Внимание", "Сервер не вернул ID заявки.")
                    else:
                        j = safe_json(resp)
                        error(self.root, "Ошибка", f"Не удалось отправить заявку\n"
                              f"HTTP {resp.status_code}\n"
                              f"{j.get('error') or j.get('message') or resp.text}")
                except Exception as e:
                    error(self.root, "Ошибка", f"Ошибка при отправке: {e}")

        self.start_polling()

    def start_polling(self):
        if not self.polling_active and self.active_orders:
            self.polling_active = True
            self.root.after(2000, self.poll_offers)

    def poll_offers(self):
        if not self.active_orders:
            self.polling_active = False
            return

        order_ids = list(self.active_orders)

        def work():
            results = []
            for oid in order_ids:
                try:
                    r = self.http.get(f"{API_URL}/market/offers/{oid}", timeout=HTTP_TIMEOUT)
                    if r.status_code == 200:
                        results.append((oid, r.json()))
                except Exception:
                    pass
            return results

        def on_ok(results):
            for order_id, offers in results:
                if order_id not in self.offers_seen:
                    self.offers_seen[order_id] = set()
                if order_id not in self.removed_offers:
                    self.removed_offers[order_id] = set()

                direction = ""
                cargo = ""
                for _item, od in self.id_map.items():
                    if int(od[0]) == int(order_id):
                        direction = od[1]
                        cargo = od[2]
                        break

                offers_list = offers.get('items') if isinstance(offers, dict) else offers
                if not isinstance(offers_list, list):
                    offers_list = []

                for off in offers_list:
                    transport_user = (off.get("transport_username") or "").strip()
                    if not transport_user:
                        continue

                    if transport_user in self.removed_offers[order_id]:
                        continue
                    if transport_user in self.offers_seen[order_id]:
                        continue

                    self.offers_seen[order_id].add(transport_user)

                    company = off.get("company", "") or ""
                    price = off.get("price", "") or ""
                    contact = off.get("contact", "") or ""

                    row_item = self.offers.insert(
                        "",
                        "end",
                        values=(UNCHECKED, company, f"{price}$"),
                    )
                    self.offers_map[row_item] = (order_id, transport_user, off)

            if self.active_orders:
                self.root.after(4000, self.poll_offers)
            else:
                self.polling_active = False

        self.run_http_async(work, on_ok=on_ok)

    def on_offer_click(self, event):
        """Ставим галочку только в колонке 'check' (первая колонка)."""
        item = self.offers.identify_row(event.y)
        col = self.offers.identify_column(event.x)
        if not item:
            return
        # '#1' — первая колонка (check)
        if col == "#1":
            values = list(self.offers.item(item, "values") or [])
            if not values:
                return "break"
            values[0] = CHECKED if values[0] == UNCHECKED else UNCHECKED
            self.offers.item(item, values=values)
            return "break"

    def open_selected_offer_contact(self):
        """Показывает информацию по ВСЕМ отмеченным откликам (☑).
        Если галочек нет — показывает по выделенным (синим) строкам.
        В окне также выводится направление заявки (из таблицы заявок).
        """

        # 1) Собираем отмеченные галочкой
        items = []
        for it in self.offers.get_children():
            vals = self.offers.item(it, "values") or ()
            if vals and len(vals) >= 1 and vals[0] == CHECKED:
                items.append(it)

        # 2) Если галочек нет — берём выделенные (может быть несколько)
        if not items:
            items = list(self.offers.selection())

        if not items:
            warn(self.root, "Ошибка", "Выберите отклики (или отметьте галочкой) в списке")
            return

        # Функция получения направления по order_id из self.id_map
        def get_direction_by_order_id(order_id) -> str:
            try:
                oid = int(order_id)
            except Exception:
                return ""
            try:
                for _item, od in self.id_map.items():
                    try:
                        if int(od[0]) == oid:
                            return str(od[1] or "")
                    except Exception:
                        continue
            except Exception:
                pass
            return ""

        lines = []
        for it in items:
            meta = self.offers_map.get(it)
            if not meta:
                continue

            order_id, _transport_user, off = meta
            direction = get_direction_by_order_id(order_id) or "—"
            company = off.get("company", "—")
            contact = off.get("contact", "—")
            price = off.get("price", "—")

            lines.append(
                f"Заявка: #{order_id}\n"
                f"Направление: {direction}\n"
                f"Компания: {company}\n"
                f"Номер тел: {contact}\n"
                f"Цена: {price}$\n"
            )

        if not lines:
            warn(self.root, "Ошибка", "Не удалось прочитать выбранные отклики")
            return

        info(
            self.root,
            f"Отклики: {len(lines)} шт.","" + ("" + ("-" * 22) + "").join(lines) if len(lines) > 1 else lines[0],
        )

    def delete_selected_offers(self):

        # 1) Пытаемся удалить по галочкам
        to_remove = []
        for item in self.offers.get_children():
            vals = self.offers.item(item, "values") or ()
            if vals and len(vals) >= 1 and vals[0] == CHECKED:
                to_remove.append(item)

        # 2) Если галочек нет — удаляем выбранные (синие)
        if not to_remove:
            to_remove = list(self.offers.selection())

        for item in to_remove:
            meta = self.offers_map.get(item)
            if meta:
                order_id, transport_user, _off = meta
                if order_id not in self.removed_offers:
                    self.removed_offers[order_id] = set()
                self.removed_offers[order_id].add(transport_user)

            try:
                self.offers.delete(item)
            except Exception:
                pass
            self.offers_map.pop(item, None)

    def close_selected_orders(self):
        # Берём строки, где стоит галочка ☑ в первой колонке
        to_close = []
        for item in self.tree.get_children():
            vals = self.tree.item(item, "values")
            if vals and vals[0] == CHECKED:
                to_close.append(item)

        # Если галочек нет — fallback на синее выделение (как раньше)
        if not to_close:
            to_close = list(self.tree.selection())

        if not to_close:
            return

        # 1) Локальные (ещё не отправленные) заявки — просто убираем
        ids_to_close = []
        for item in list(to_close):
            if item not in self.id_map:
                continue
            order = self.id_map[item]
            oid = order[0]
            if oid is None or int(oid) < 0:
                self.tree.delete(item)
                self.id_map.pop(item, None)
                to_close.remove(item)
            else:
                ids_to_close.append(int(oid))

        if not ids_to_close:
            return

        def work():
            # server.py ожидает {"ids": [..]} и закрывает заявки + market_orders
            return self.http.post(f"{API_URL}/orders/close", json={"ids": ids_to_close}, timeout=HTTP_TIMEOUT)

        def on_ok(resp):
            if getattr(resp, "status_code", None) not in (200, 201):
                j = safe_json(resp) if hasattr(resp, "status_code") else {}
                error(self.root, "Ошибка", f"Не удалось закрыть заявки")
                return

            # Удаляем закрытые заявки из UI
            for item in list(to_close):
                meta = self.id_map.get(item)
                if not meta:
                    continue
                oid = int(meta[0])
                self.active_orders.discard(oid)
                self.offers_seen.pop(oid, None)
                self.removed_offers.pop(oid, None)

                # удаляем отклики по этой заявке
                for off_item, (o, _tu, _off) in list(self.offers_map.items()):
                    if int(o) == oid:
                        self.offers.delete(off_item)
                        self.offers_map.pop(off_item, None)

                self.tree.delete(item)
                self.id_map.pop(item, None)

            if not self.active_orders:
                self.polling_active = False

        self.run_http_async(work, on_ok=on_ok)



# ================= Login window =================

def login_to_server(root: tk.Tk) -> Optional[str]:
    win = tk.Toplevel(root)
    win.title("Manager — Вход / Регистрация")
    win.geometry("680x357")
    win.resizable(False, False)
    win.configure(bg=BG_MAIN)
    win.grab_set()
    disable_tk_bell(win)
    apply_global_font(win)
    _set_window_icon(win)

    canvas = tk.Canvas(win, width=680, height=357, highlightthickness=0)
    canvas.place(x=0, y=0)

    bg_img = load_login_image(LOGIN_BG_PATH)
    if bg_img is not None:
        canvas.create_image(0, 0, anchor="nw", image=bg_img)
        canvas.bg_img = bg_img
    else:
        canvas.configure(bg=BG_MAIN)

    panel = tk.Frame(canvas, bg=BG_PANEL)
    panel.place(relx=0.5, rely=0.5, anchor="c", width=360, height=330)

    title = tk.Label(panel, text="Manager", bg=BG_PANEL, fg=FG_TEXT, font=(APP_FONT_FAMILY, 16, "bold"))
    title.pack(pady=(18, 10))

    form = tk.Frame(panel, bg=BG_PANEL)
    form.pack(fill="both", expand=True, padx=18, pady=(5, 10))

    def make_labeled_entry(parent, label: str, show: str = ""):
        lbl = tk.Label(parent, text=label, bg=BG_PANEL, fg=FG_TEXT)
        ent = tk.Entry(parent, bg=ENTRY_BG, fg=ENTRY_FG, insertbackground="white", show=show)
        return lbl, ent

    lbl_user, user_e = make_labeled_entry(form, "Логин")
    lbl_pass, pass_e = make_labeled_entry(form, "Пароль", show="*")

    lbl_user.pack(anchor="w", pady=(6, 2))
    user_e.pack(fill="x")
    lbl_pass.pack(anchor="w", pady=(6, 2))
    pass_e.pack(fill="x")

    remember = tk.BooleanVar(value=True)
    tk.Checkbutton(
        panel,
        text="Запомнить токен",
        variable=remember,
        bg=BG_PANEL,
        fg=FG_TEXT,
        selectcolor=BG_PANEL,
        activebackground=BG_PANEL,
        activeforeground=FG_TEXT,
    ).pack(pady=(0, 8))

    result = {"token": None}

    def do_login():
        u = user_e.get().strip()
        p = pass_e.get().strip()
        if not u or not p:
            error(win, "Ошибка", "Введите логин и пароль")
            return

        try:
            r = requests.post(
                f"{API_URL}/login",
                json={"username": u, "password": p, "device_id": get_device_id(), "app": "manager"},
                timeout=HTTP_TIMEOUT,
            )
            if r.status_code != 200:
                j = safe_json(r)
                # License check is centralized: if key is invalid, stop the whole chain and exit.
                if isinstance(j, dict) and j.get("error") in (
                    "license_inactive", "license_expired", "license_not_found",
                    "license_app_mismatch", "device_limit_reached",
                ):
                    exit_app(win, "Ключ продукта недействителен")
                else:
                    error(win, "Ошибка", "Не удалось авторизоваться")
                return

            data = r.json()
            if isinstance(data, dict) and data.get('license_valid') is False:
                exit_app(win, 'Ключ продукта недействителен')
            token = data.get("token")
            role = (data.get("role") or "").lower()

            if role not in ("manager", "admin"):
                error(
                    win,
                    "Ошибка",
                    "Непредвиденная ошибка"
                )
                return

            if not token:
                error(win, "Ошибка", "Сервер не вернул токен")
                return

            if remember.get():
                try:
                    with open("manager_auth_token.txt", "w", encoding="utf-8") as f:
                        f.write(token)
                except Exception:
                    pass

            result["token"] = token
            win.destroy()

        except Exception as e:
            error(win, "Ошибка", f"Не удалось подключиться к серверу:\n{e}")

    def open_register_window(parent_win: tk.Toplevel):
        reg = tk.Toplevel(parent_win)
        reg.title("Регистрация")
        reg.geometry("420x690")
        reg.resizable(False, False)
        reg.configure(bg=BG_MAIN)
        reg.grab_set()
        disable_tk_bell(reg)
        apply_global_font(reg)
        _set_window_icon(reg)

        panel2 = tk.Frame(reg, bg=BG_PANEL)
        panel2.place(relx=0.5, rely=0.5, anchor="c", width=420, height=690)

        tk.Label(
            panel2,
            text="Регистрация аккаунта",
            bg=BG_PANEL,
            fg=FG_TEXT,
            font=(APP_FONT_FAMILY, 14, "bold"),
        ).pack(pady=(16, 10))

        def labeled(parent, label, show=""):
            tk.Label(parent, text=label, bg=BG_PANEL, fg=FG_TEXT).pack(anchor="w", padx=18, pady=(8, 2))
            e = tk.Entry(parent, bg=ENTRY_BG, fg=ENTRY_FG, insertbackground="white", show=show)
            e.pack(fill="x", padx=18)
            return e

        u_e = labeled(panel2, "Логин")
        p_e = labeled(panel2, "Пароль", show="*")
        phone_e = labeled(panel2, "Номер телефона")
        email_e = labeled(panel2, "Почта (email)")
        company_e = labeled(panel2, "Название компании")
        key_e = labeled(panel2, "Ключ продукта")

        def do_register_real():
            u = u_e.get().strip()
            p = p_e.get().strip()
            phone = phone_e.get().strip()
            email = email_e.get().strip()
            company_name = company_e.get().strip()
            key = key_e.get().strip()

            if not u or not p or not phone or not email or not company_name or not key:
                error(reg, "Ошибка", "Заполните все поля")
                return

            try:
                r = requests.post(
                    f"{API_URL}/register",
                    json={
                        "username": u,
                        "password": p,
                        "email": email,
                        "phone": phone,
                        "company_name": company_name,
                        "license_key": key,
                        "device_id": get_device_id(),
                        "role": "manager",
                    },
                    timeout=HTTP_TIMEOUT,
                )

                if r.status_code != 201:
                    j = safe_json(r)
                    if isinstance(j, dict) and j.get("error") in (
                        "license_inactive", "license_expired", "license_not_found",
                        "license_app_mismatch", "device_limit_reached",
                    ):
                        exit_app(reg, "Ключ продукта недействителен")
                    error(reg, "Ошибка", "Не удалось зарегистрироваться")
                    return

                info(reg, "Готово", "Аккаунт создан")
                reg.destroy()

                user_e.delete(0, tk.END)
                user_e.insert(0, u)
                pass_e.delete(0, tk.END)
                pass_e.focus_set()

            except Exception as e:
                error(reg, "Ошибка", f"Не удалось подключиться к серверу:\n{e}")

        tk.Button(panel2, text="Зарегистрироваться", bg=ACCENT, fg="white", command=do_register_real).pack(
            fill="x", padx=18, pady=(10, 10)
        )

        reg.bind("<Return>", lambda _e: do_register_real())
        reg.bind("<Escape>", lambda _e: reg.destroy())
        u_e.focus_set()

    tk.Button(panel, text="Войти", bg=ACCENT, fg="white", command=do_login).pack(fill="x", padx=18, pady=(0, 8))
    tk.Button(panel, text="Регистрация", bg="#607D8B", fg="white", command=lambda: open_register_window(win)).pack(
        fill="x", padx=18, pady=(0, 12)
    )

    win.bind("<Return>", lambda _e: do_login())
    win.bind("<Escape>", lambda _e: win.destroy())
    user_e.focus_set()

    root.wait_window(win)
    return result["token"]


def try_restore_token() -> Optional[str]:
    p = "manager_auth_token.txt"
    if not os.path.exists(p):
        return None

    try:
        t = open(p, "r", encoding="utf-8").read().strip()
        if not t:
            return None

        chk = requests.get(
            f"{API_URL}/me",
            headers={"Authorization": f"Bearer {t}"},
            timeout=HTTP_TIMEOUT,
        )

        if chk.status_code in (401, 403):
            try:
                os.remove(p)
            except Exception:
                pass
            return None

        if chk.status_code != 200:
            return None

        return t

    except Exception:
        return None


if __name__ == "__main__":
    root = tk.Tk()
    apply_global_font(root)
    disable_tk_bell(root)

    # можно менять размер главного окна (по умолчанию так и есть, но пусть будет явно)
    root.resizable(True, True)

    root.withdraw()

    auth_token = try_restore_token()
    if not auth_token:
        auth_token = login_to_server(root)

    if auth_token:
        root.deiconify()
        app = AppGUI(root, auth_token)

        def on_close():
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", on_close)
        root.mainloop()
    else:
        root.destroy()
