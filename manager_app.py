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

import datetime
import calendar

import tkinter as tk
from tkinter import ttk

import requests
# manager_app.py
# Отправляет заявки на server.py
# pip install requests

import requests
import os
import json

from market_stats_popup import open_market_stats_popup

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

# ===== Login UI assets (site-matched branding) =====
LOGIN_ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "icon.ico")
SITE_LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "icon.png")
LOGIN_BG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "login_background.jpg")

API_URL = os.getenv("API_URL", "http://34.179.169.197")
HTTP_TIMEOUT = 6

# Token file (persist across sessions regardless of current working directory)
def app_base_dir() -> str:
    """Папка запуска: рядом с .exe (PyInstaller) или рядом со скриптом."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

TOKEN_FILE = os.path.join(app_base_dir(), "manager_auth_token.txt")

# ================== THEME ==================
# Rivee website-inspired dark glass theme
BG_MAIN = "#071220"
BG_PANEL = "#0c1726"
BG_CARD = "#102133"

FG_TEXT = "#eef8ff"
FG_MUTED = "#9db9ce"
ACCENT = "#2aa8ff"

ENTRY_BG = "#091725"
ENTRY_FG = "#ffffff"
PLACEHOLDER_FG = "#6b7280"

BTN_BG = "#112235"
BTN_HOVER = "#17314a"
BTN_DANGER = "#ef4444"
BTN_SUCCESS = "#1fa971"
BTN_WARN = "#1c7cc2"
BTN_SECONDARY = "#16314a"

BORDER = "#20415f"

CHECKED = "☑"
UNCHECKED = "☐"

# ===== Global font (applies to whole app) =====
APP_FONT_FAMILY = os.getenv("APP_FONT_FAMILY", "Segoe UI Variable")
APP_FONT_SIZE = int(os.getenv("APP_FONT_SIZE", "11"))
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


# ================== User-friendly API errors ==================
SHOW_TECH_ERRORS = os.getenv("SHOW_TECH_ERRORS", "0").strip() == "1"

# Сервер обычно отдаёт JSON вида: {"error": "...", "message": "..."}.
# Здесь мы переводим "технические" коды в понятные сообщения для обычного пользователя.
ERROR_CODE_TO_TEXT = {
    # Auth / account
    "invalid_credentials": "Неверный логин или пароль.",
    "user_not_found": "Аккаунт не найден. Проверьте логин.",
    "username_taken": "Этот логин уже занят. Придумайте другой.",
    "username_exists": "Этот логин уже занят. Придумайте другой.",
    "email_invalid": "Некорректный email. Проверьте написание.",
    "email_taken": "Этот email уже используется.",
    "phone_invalid": "Некорректный номер телефона. Проверьте формат.",
    "password_too_short": "Пароль слишком короткий. Сделайте пароль длиннее.",
    "password_weak": "Слишком простой пароль. Добавьте цифры и/или разные символы.",

    # License
    "license_not_found": "Ключ продукта не найден. Проверьте, что вы ввели его без ошибок.",
    "license_inactive": "Ключ продукта не активен. Обратитесь к администратору.",
    "license_expired": "Срок действия ключа истёк. Обратитесь к администратору.",
    "license_app_mismatch": "Этот ключ предназначен для другой версии программы.",
    "device_limit_reached": "Достигнут лимит устройств для этого ключа. Обратитесь к администратору.",

    # Company ↔ key binding (то, что ты попросил)
    "license_company_required": "Для этого ключа не задана компания. Обратитесь к администратору.",
    "company_name_required": "Укажите название компании.",
    "company_mismatch": (
        "Название компании не совпадает с компанией, указанной при покупке ключа."
        "Проверьте написание (пробелы, регистр) или обратитесь к администратору."
    ),

    # Generic / permissions
    "forbidden": "Недостаточно прав для выполнения действия.",
    "unauthorized": "Сессия недействительна. Войдите заново.",
}

def format_api_error(resp: Any, fallback: str = "Произошла ошибка. Попробуйте ещё раз.") -> str:
    """Возвращает понятный текст ошибки для диалогового окна."""
    status = getattr(resp, "status_code", None)
    j = safe_json(resp) if hasattr(resp, "status_code") else {}
    code = ""
    if isinstance(j, dict):
        code = (j.get("error") or j.get("code") or "").strip()

    # 401/403 без конкретики
    if status in (401, 403) and not code:
        code = "unauthorized"

    text = ERROR_CODE_TO_TEXT.get(code) if code else None
    if not text:
        # иногда сервер кладёт дружелюбное поле message
        if isinstance(j, dict):
            msg = (j.get("message") or "").strip()
            if msg and len(msg) <= 220:
                text = msg
    if not text:
        text = fallback

    if SHOW_TECH_ERRORS:
        tech = []
        if status is not None:
            tech.append(f"HTTP {status}")
        if code:
            tech.append(f"code={code}")
        # коротко добавим message/error, если есть
        if isinstance(j, dict):
            extra = (j.get("message") or j.get("error") or "").strip()
            if extra and extra != code:
                tech.append(extra[:180])
        if tech:
            text = text + "\n\n[Тех. детали: " + " | ".join(tech) + "]"
    return text





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


def load_brand_image(path: str, size: int = 28):
    if not path or not os.path.exists(path):
        return None
    try:
        from PIL import Image, ImageTk  # type: ignore

        img = Image.open(path).convert("RGBA")
        img = img.resize((size, size))
        return ImageTk.PhotoImage(img)
    except Exception:
        pass
    try:
        img = tk.PhotoImage(file=path)
        if size > 0:
            subsample = max(1, img.width() // size)
            if subsample > 1:
                img = img.subsample(subsample, subsample)
        return img
    except Exception:
        return None


def maximize_window(win: tk.Tk) -> None:
    try:
        win.state("zoomed")
        return
    except Exception:
        pass
    try:
        win.geometry(f"{win.winfo_screenwidth()}x{win.winfo_screenheight()}+0+0")
    except Exception:
        pass


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




class RoundedButton(tk.Canvas):
    """
    Canvas-based rounded button (works on all platforms in pure Tkinter).
    Supports .config(...) like tk.Button for common options: text, command, state, bg, fg, width, padx, pady.
    """
    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        command,
        *,
        bg: str,
        fg: str = "white",
        hover_bg: Optional[str] = None,
        active_bg: Optional[str] = None,
        radius: int = 12,
        padx: int = 14,
        pady: int = 9,
        font=APP_FONT,
        cursor: str = "hand2",
        disabled_fg: str = "#6b7280",
    ):
        super().__init__(parent, highlightthickness=0, bd=0, relief="flat", bg=parent.cget("bg"))
        self._text = text
        self._command = command
        self._radius = max(6, int(radius))
        self._padx = int(padx)
        self._pady = int(pady)
        self._font = font
        self._cursor = cursor

        self._base_bg = bg
        self._hover_bg = hover_bg or BTN_HOVER
        self._active_bg = active_bg or ACCENT
        self._fg = fg
        self._disabled_fg = disabled_fg

        self._state = "normal"  # normal/disabled

        self.configure(cursor=self._cursor)

        # Items
        self._rect_id = None
        self._text_id = None

        # Events
        self.bind("<Configure>", lambda _e: self._redraw(), add="+")
        self.bind("<Button-1>", self._on_click, add="+")
        self.bind("<Enter>", self._on_enter, add="+")
        self.bind("<Leave>", self._on_leave, add="+")

        self._redraw()

    # ---- drawing ----
    def _rounded_rect_points(self, x1, y1, x2, y2, r):
        r = min(r, int((x2 - x1) / 2), int((y2 - y1) / 2))
        return [
            x1+r, y1,
            x2-r, y1,
            x2, y1,
            x2, y1+r,
            x2, y2-r,
            x2, y2,
            x2-r, y2,
            x1+r, y2,
            x1, y2,
            x1, y2-r,
            x1, y1+r,
            x1, y1
        ]

    def _ensure_size(self):
        # Compute a "natural" size using Tk font metrics
        try:
            import tkinter.font as tkfont
            f = tkfont.Font(font=self._font)
            tw = f.measure(self._text)
            th = f.metrics("linespace")
        except Exception:
            tw, th = (len(self._text) * 7, 14)

        w = max(40, tw + self._padx * 2)
        h = max(28, th + self._pady * 2)
        try:
            if int(self.cget("width")) == w and int(self.cget("height")) == h:
                return
        except Exception:
            pass
        super().configure(width=w, height=h)

    def _redraw(self):
        self._ensure_size()
        w = int(self.cget("width"))
        h = int(self.cget("height"))
        r = min(self._radius, max(6, (min(w, h) // 2) - 1))

        self.delete("all")

        fill = self._base_bg
        if self._state == "disabled":
            fill = BORDER

        pts = self._rounded_rect_points(1, 1, w-1, h-1, r)
        self._rect_id = self.create_polygon(
            pts,
            smooth=True,
            splinesteps=12,
            fill=fill,
            outline=fill,
        )
        self._text_id = self.create_text(
            w // 2,
            h // 2,
            text=self._text,
            fill=(self._disabled_fg if self._state == "disabled" else self._fg),
            font=self._font,
        )

    # ---- interactions ----
    def _set_bg(self, color: str):
        if self._rect_id is not None:
            self.itemconfigure(self._rect_id, fill=color, outline=color)

    def _on_enter(self, _e=None):
        if self._state == "disabled":
            return
        self._set_bg(self._hover_bg)

    def _on_leave(self, _e=None):
        if self._state == "disabled":
            return
        self._set_bg(self._base_bg)

    def _on_click(self, _e=None):
        if self._state == "disabled":
            return
        # brief active flash
        self._set_bg(self._active_bg)
        self.after(90, lambda: self._set_bg(self._hover_bg))
        try:
            if callable(self._command):
                self._command()
        except Exception:
            pass

    # ---- public API (minimal Button-like) ----
    def config(self, **kwargs):
        # Tk uses both config and configure
        self.configure(**kwargs)

    def configure(self, cnf=None, **kwargs):
        cnf = cnf or {}
        opts = dict(cnf, **kwargs)

        if "text" in opts:
            self._text = str(opts.pop("text"))
        if "command" in opts:
            self._command = opts.pop("command")
        if "state" in opts:
            self._state = str(opts.pop("state"))
        if "bg" in opts:
            self._base_bg = opts.pop("bg")
        if "fg" in opts:
            self._fg = opts.pop("fg")
        if "hover_bg" in opts:
            self._hover_bg = opts.pop("hover_bg")
        if "active_bg" in opts:
            self._active_bg = opts.pop("active_bg")
        if "radius" in opts:
            self._radius = int(opts.pop("radius"))
        if "padx" in opts:
            self._padx = int(opts.pop("padx"))
        if "pady" in opts:
            self._pady = int(opts.pop("pady"))
        if "font" in opts:
            self._font = opts.pop("font")
        if "cursor" in opts:
            self._cursor = opts.pop("cursor")
            super().configure(cursor=self._cursor)

        # width/height should still work as normal Canvas options
        super().configure(opts)
        self._redraw()

    def cget(self, key):
        if key == "text":
            return self._text
        if key == "state":
            return self._state
        if key == "bg":
            return self._base_bg
        if key == "fg":
            return self._fg
        return super().cget(key)


def modern_button(parent: tk.Misc, text: str, command, variant: str = "default"):
    """Rounded modern button. Variants: default|accent|success|danger|warn|secondary"""
    bg_map = {
        "default": BTN_BG,
        "accent": ACCENT,
        "success": BTN_SUCCESS,
        "danger": BTN_DANGER,
        "warn": BTN_WARN,
        "secondary": BTN_SECONDARY,
    }
    base_bg = bg_map.get(variant, BTN_BG)

    # Accent buttons stay accent on hover for the "iOS pill" look
    hover = base_bg if variant in ("accent", "success", "danger", "warn") else BTN_HOVER
    font = APP_FONT_BOLD if variant in ("accent", "success", "danger", "warn") else APP_FONT

    return RoundedButton(
        parent,
        text=text,
        command=command,
        bg=base_bg,
        hover_bg=hover,
        active_bg=ACCENT,
        radius=14,
        padx=16,
        pady=9,
        font=font,
    )

def style_entry(e: tk.Entry) -> tk.Entry:
    """Apply modern input styling to a tk.Entry."""
    try:
        e.config(
            bg=ENTRY_BG,
            fg=ENTRY_FG,
            insertbackground="white",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
    except Exception:
        pass
    return e

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


class RoundedCard(tk.Canvas):
    """Canvas with rounded rectangle background and an inner frame you can pack into."""
    def __init__(self, parent: tk.Misc, *, bg: str, radius: int = 18, padding: int = 16):
        super().__init__(parent, highlightthickness=0, bd=0, relief="flat", bg=parent.cget("bg"))
        self._bg = bg
        self._radius = max(8, int(radius))
        self._padding = int(padding)

        self.inner = tk.Frame(self, bg=self._bg)
        self._win_id = self.create_window(0, 0, window=self.inner, anchor="nw")

        self.bind("<Configure>", self._on_resize, add="+")
        self._on_resize()

    def _rounded_rect(self, x1, y1, x2, y2, r):
        r = min(r, int((x2 - x1) / 2), int((y2 - y1) / 2))
        pts = [
            x1+r, y1,
            x2-r, y1,
            x2, y1,
            x2, y1+r,
            x2, y2-r,
            x2, y2,
            x2-r, y2,
            x1+r, y2,
            x1, y2,
            x1, y2-r,
            x1, y1+r,
            x1, y1
        ]
        return pts

    def _on_resize(self, _e=None):
        w = max(1, self.winfo_width())
        h = max(1, self.winfo_height())
        self.delete("bg")
        r = min(self._radius, max(8, (min(w, h) // 2) - 2))
        pts = self._rounded_rect(2, 2, w-2, h-2, r)
        self.create_polygon(pts, smooth=True, splinesteps=18, fill=self._bg, outline=self._bg, tags="bg")
        self.coords(self._win_id, self._padding, self._padding)
        self.itemconfigure(self._win_id, width=max(1, w - self._padding*2), height=max(1, h - self._padding*2))

def dark_message(parent: tk.Misc, title: str, text: str, kind: str = "info") -> None:
    """
    kind: info | warning | error
    Premium rounded dialog (rounded container + rounded button).
    """
    win = tk.Toplevel(parent)
    win.title(title)
    _set_window_icon(win)
    win.configure(bg=BG_MAIN)

    # modal
    win.transient(parent.winfo_toplevel())
    win.grab_set()
    disable_tk_bell(win)

    win.update_idletasks()
    screen_w = win.winfo_screenwidth()
    screen_h = win.winfo_screenheight()

    max_text_w = min(760, int(screen_w * 0.70))
    min_win_w = 420
    min_win_h = 190

    # Outer rounded card
    card = RoundedCard(win, bg=BG_PANEL, radius=18, padding=18)
    card.pack(fill="both", expand=True, padx=16, pady=16)

    # Body (text)
    msg = tk.Label(
        card.inner,
        text=text,
        bg=BG_PANEL,
        fg=FG_TEXT,
        justify="left",
        anchor="nw",
        wraplength=max_text_w,
    )
    msg.pack(fill="both", expand=True)

    # Footer
    footer = tk.Frame(card.inner, bg=BG_PANEL)
    footer.pack(fill="x", pady=(14, 0))

    def close():
        try:
            win.grab_release()
        except Exception:
            pass
        win.destroy()

    ok_btn = modern_button(footer, "OK", close, variant="accent")
    ok_btn.pack(side="right")

    # Enter/Esc
    win.bind("<Return>", lambda _e: close())
    win.bind("<Escape>", lambda _e: close())
    win.update_idletasks()

    # Auto-size
    req_w = max(min_win_w, win.winfo_reqwidth())
    req_h = max(min_win_h, win.winfo_reqheight())
    max_win_w = int(screen_w * 0.85)
    max_win_h = int(screen_h * 0.85)
    req_w = min(req_w, max_win_w)
    req_h = min(req_h, max_win_h)

    # Center
    try:
        parent_win = parent.winfo_toplevel()
        px = parent_win.winfo_rootx()
        py = parent_win.winfo_rooty()
        pw = parent_win.winfo_width()
        ph = parent_win.winfo_height()
        x = px + max(0, (pw - req_w) // 2)
        y = py + max(0, (ph - req_h) // 2)
    except Exception:
        x = (screen_w - req_w) // 2
        y = (screen_h - req_h) // 2

    win.geometry(f"{req_w}x{req_h}+{x}+{y}")
    try:
        ok_btn.focus_set()
    except Exception:
        pass

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


# ================== Date picker (calendar popup) ==================
def _parse_ddmmyyyy(s: str):
    s = (s or "").strip()
    try:
        d, m, y = s.split(".")
        return datetime.date(int(y), int(m), int(d))
    except Exception:
        return None

def _format_ddmmyyyy(d: datetime.date) -> str:
    return f"{d.day:02d}.{d.month:02d}.{d.year:04d}"

class CalendarPopup(tk.Toplevel):
    """Простой календарь без сторонних библиотек. Возвращает дату в формате ДД.ММ.ГГГГ."""
    def __init__(self, parent: tk.Misc, on_pick, initial: Optional[datetime.date] = None):
        super().__init__(parent.winfo_toplevel())
        self.configure(bg=BG_PANEL)
        self.title("Выберите дату")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        disable_tk_bell(self)
        _set_window_icon(self)

        self._on_pick = on_pick

        today = datetime.date.today()
        self._shown = initial or today
        self._year = self._shown.year
        self._month = self._shown.month

        header = tk.Frame(self, bg=BG_PANEL)
        header.pack(fill="x", padx=10, pady=(10, 6))

        btn_prev = tk.Button(
            header, text="‹", bg=BG_MAIN, fg=FG_TEXT, bd=0, width=3,
            activebackground=BG_MAIN, activeforeground=FG_TEXT,
            command=self._prev_month
        )
        btn_prev.pack(side="left")

        self._title_lbl = tk.Label(header, text="", bg=BG_PANEL, fg=FG_TEXT, font=APP_FONT_BOLD)
        self._title_lbl.pack(side="left", expand=True)

        btn_next = tk.Button(
            header, text="›", bg=BG_MAIN, fg=FG_TEXT, bd=0, width=3,
            activebackground=BG_MAIN, activeforeground=FG_TEXT,
            command=self._next_month
        )
        btn_next.pack(side="right")

        # Weekday header
        dow = tk.Frame(self, bg=BG_PANEL)
        dow.pack(fill="x", padx=10)
        for i, name in enumerate(["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]):
            tk.Label(dow, text=name, bg=BG_PANEL, fg=FG_TEXT, width=4).grid(row=0, column=i, padx=1, pady=(0, 4))

        self._grid = tk.Frame(self, bg=BG_PANEL)
        self._grid.pack(fill="both", padx=10, pady=(0, 10))

        self.bind("<Escape>", lambda _e: self._close())
        self._render()

        # Центрируем
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def _prev_month(self):
        if self._month == 1:
            self._month = 12
            self._year -= 1
        else:
            self._month -= 1
        self._render()

    def _next_month(self):
        if self._month == 12:
            self._month = 1
            self._year += 1
        else:
            self._month += 1
        self._render()

    def _pick(self, day: int):
        d = datetime.date(self._year, self._month, day)
        try:
            self._on_pick(d)
        finally:
            self._close()

    def _render(self):
        # Заголовок месяца
        month_name = [
            "Январь","Февраль","Март","Апрель","Май","Июнь",
            "Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"
        ][self._month - 1]
        self._title_lbl.config(text=f"{month_name} {self._year}")

        # очистка сетки
        for w in self._grid.winfo_children():
            w.destroy()

        cal = calendar.Calendar(firstweekday=0)  # 0=Monday
        weeks = cal.monthdayscalendar(self._year, self._month)

        # Кнопки дней
        for r, week in enumerate(weeks):
            for c, day in enumerate(week):
                if day == 0:
                    tk.Label(self._grid, text=" ", bg=BG_PANEL, width=4).grid(row=r, column=c, padx=1, pady=1)
                    continue

                is_today = (day == datetime.date.today().day and self._month == datetime.date.today().month and self._year == datetime.date.today().year)
                btn = tk.Button(
                    self._grid,
                    text=str(day),
                    width=4,
                    bg=ACCENT if is_today else BG_MAIN,
                    fg="white" if is_today else FG_TEXT,
                    bd=0,
                    activebackground=ACCENT,
                    activeforeground="white",
                    command=lambda d=day: self._pick(d),
                )
                btn.grid(row=r, column=c, padx=1, pady=1)



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
        maximize_window(root)

        # Иконка главного окна
        try:
            if LOGIN_ICON_PATH and os.path.exists(LOGIN_ICON_PATH):
                root.iconbitmap(LOGIN_ICON_PATH)
        except Exception:
            pass

        self.init_styles()
        self.build_top_buttons()
        self.build_left_panel()
        self.build_center_panel()
        # self.build_right_orders_panel()  # removed: single unified orders panel
        self.build_offers_storage()

        # Offers dialog window (toggle)
        self.offers_win = None
        self.offers_dialog_tree = None
        self.offers_dialog_map = {}
        self.offers_dialog_search = None
        self.offers_dialog_search_var = None
        self.offers_dialog_placeholder = "Введите для поиска (напр. город, компания, цена)"

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

        # Global ttk defaults
        style.configure(".", font=APP_FONT)
        style.configure("TFrame", background=BG_MAIN)
        style.configure("TLabel", background=BG_PANEL, foreground=FG_TEXT, font=APP_FONT)

        # Treeview (tables) — "card" look
        style.configure(
            "Dark.Treeview",
            background=BG_CARD,
            foreground=FG_TEXT,
            fieldbackground=BG_CARD,
            rowheight=36,
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
            foreground=FG_MUTED,
            relief="flat",
            font=APP_FONT_BOLD,
        )

        # --- thin modern scrollbars (dark + subtle) ---
        style.configure(
            "Thin.Vertical.TScrollbar",
            gripcount=0,
            borderwidth=0,
            relief="flat",
            troughcolor=BG_CARD,
            background=BORDER,
            darkcolor=BORDER,
            lightcolor=BORDER,
            arrowcolor=BG_CARD,
            width=10,
        )
        style.configure(
            "Thin.Horizontal.TScrollbar",
            gripcount=0,
            borderwidth=0,
            relief="flat",
            troughcolor=BG_CARD,
            background=BORDER,
            darkcolor=BORDER,
            lightcolor=BORDER,
            arrowcolor=BG_CARD,
            width=10,
        )
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
        left = tk.Frame(self.root, bg=BG_PANEL, padx=12, pady=12, highlightthickness=1, highlightbackground=BORDER)
        left.pack(side="left", fill="y", padx=(16, 0), pady=(0, 16))

        fields = [
            ("Откуда", "Введите город/точку отправления"),
            ("Куда", "Введите город/точку назначения"),
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

            # Спец-случай: поле "Дата" + кнопка календаря справа (квадрат той же высоты)
            if label == "Дата":
                row = tk.Frame(left, bg=BG_PANEL)
                row.pack(fill="x", pady=4)

                e = style_entry(tk.Entry(row, width=29))
                e.pack(side="left", fill="x", expand=True)

                def open_calendar(_entry=e):
                    # initial date: from entry if user already typed a date
                    current = self.get_entry_value(_entry)
                    initial = _parse_ddmmyyyy(current)
                    def on_pick(d):
                        # вставляем в нужном формате
                        self._ph_clear(_entry)
                        _entry.delete(0, tk.END)
                        _entry.insert(0, _format_ddmmyyyy(d))
                        _entry.config(fg=ENTRY_FG)
                    CalendarPopup(self.root, on_pick=on_pick, initial=initial)

                # квадратная кнопка с иконкой календаря
                cal_btn = modern_button(row, "📅", open_calendar, variant="default")
                cal_btn.config(width=3, padx=0, pady=8)
                cal_btn.pack(side="left", padx=(8, 0))

            else:
                e = style_entry(tk.Entry(left, width=35))
                e.pack(pady=4)

            self.entries[label] = e
            self.entry_placeholders[label] = placeholder
            self.add_placeholder(e, placeholder)
            e.bind("<Return>", lambda _e: self.add_order(), add="+")
            e.bind("<KP_Enter>", lambda _e: self.add_order(), add="+")

    def build_top_buttons(self):
        top = tk.Frame(self.root, bg=BG_PANEL, padx=18, pady=14, highlightthickness=1, highlightbackground=BORDER)
        top.pack(fill="x", padx=16, pady=(14, 10))

        brand = tk.Frame(top, bg=BG_PANEL)
        brand.pack(side="left", padx=(0, 18))

        self._brand_logo = load_brand_image(SITE_LOGO_PATH, size=28)
        if self._brand_logo is not None:
            tk.Label(brand, image=self._brand_logo, bg=BG_PANEL).pack(side="left", padx=(0, 10))

        tk.Label(
            brand,
            text="Rivee",
            bg=BG_PANEL,
            fg=ACCENT,
            font=(APP_FONT_FAMILY, APP_FONT_SIZE + 6, "bold"),
        ).pack(side="left")

        actions = tk.Frame(top, bg=BG_PANEL)
        actions.pack(side="left")

        modern_button(actions, "➕ Добавить", self.add_order, variant="accent").pack(side="left", padx=6)

        # безопасная привязка (на случай, если метод переименован/утрачен при мердже)
        send_cb = getattr(self, "save_and_run", None)
        if not callable(send_cb):
            send_cb = getattr(self, "save_and_run_orders", None)
        if not callable(send_cb):
            send_cb = getattr(self, "save_and_publish", None)
        if not callable(send_cb):
            send_cb = lambda: error(self.root, "Ошибка", "Не найдена функция отправки заявок (save_and_run)")
        modern_button(actions, "💾 Отправить", send_cb, variant="success").pack(side="left", padx=6)

        close_cb = getattr(self, "close_selected_orders", None)
        if not callable(close_cb):
            close_cb = getattr(self, "close_selected_order", None)
        if not callable(close_cb):
            close_cb = lambda: error(self.root, "Ошибка", "Не найдена функция закрытия заявок (close_selected_orders)")
        modern_button(actions, "🗑 Закрыть заявки", close_cb, variant="warn").pack(side="left", padx=6)

        self.btn_toggle_offers = modern_button(
            actions,
            "👁 Отклики",
            self.toggle_offers_window,
            variant="default",
        )
        self.btn_toggle_offers.pack(side="left", padx=6)

        modern_button(actions, "🔄 Обновить заявки", self.refresh_orders, variant="secondary").pack(side="left", padx=6)
        modern_button(actions, "📊 Статистика", self.open_market_stats_window, variant="default").pack(side="left", padx=6)
        modern_button(top, "Выйти", self.logout, variant="danger").pack(side="right")


    def logout(self):
        try:
            self.polling_active = False
            self.active_orders.clear()
        except Exception:
            pass

        try:
            if getattr(self, "offers_win", None) is not None and self.offers_win.winfo_exists():
                self.offers_win.destroy()
        except Exception:
            pass

        try:
            popup = getattr(self.root, "_market_stats_popup", None)
            if popup is not None:
                popup.close()
        except Exception:
            pass

        try:
            if os.path.exists(TOKEN_FILE):
                os.remove(TOKEN_FILE)
        except Exception:
            pass

        try:
            self.root.withdraw()
        except Exception:
            pass

        for widget in list(self.root.winfo_children()):
            try:
                widget.destroy()
            except Exception:
                pass

        token = login_to_server(self.root)
        if not token:
            try:
                self.root.destroy()
            except Exception:
                pass
            return

        try:
            self.root.deiconify()
        except Exception:
            pass
        self.root._app = AppGUI(self.root, token)  # type: ignore[attr-defined]

    def open_market_stats_window(self):
        open_market_stats_popup(
            self.root,
            self.http,
            API_URL,
            title="Статистика рынка",
            icon_path=LOGIN_ICON_PATH,
            app_font=APP_FONT,
            app_font_bold=APP_FONT_BOLD,
            style_entry=style_entry,
            modern_button=modern_button,
        )

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


        # Подгоняем ширины колонок под текущую ширину таблицы (растягиваем на всю панель)
        # и запрещаем пользователю менять ширины перетаскиванием.
        self._orders_col_weights = {
            "dir": 0.34,
            "cargo": 0.24,
            "truck": 0.18,
            "price": 0.10,
            "info": 0.14,
        }
        self.tree.bind("<Configure>", lambda _e: self._fit_orders_columns(), add="+")
        # заблокируем ресайз колонок мышкой (drag по separator)
        self.tree.bind("<B1-Motion>", self._block_tree_column_resize, add="+")
        self._fit_orders_columns()

    # ================= Offers table =================
    # ================= Right panel: Orders (instead of offers) =================
    def build_right_orders_panel(self):
        right = tk.Frame(self.root, bg=BG_PANEL, padx=16, pady=16)
        right.pack(side="right", fill="y")

        tk.Label(
            right,
            text="Заявки",
            bg=BG_PANEL,
            fg=FG_TEXT,
            font=APP_FONT_BOLD,
        ).pack(anchor="w", pady=(0, 10))

        table_wrap = tk.Frame(right, bg=BG_PANEL)
        table_wrap.pack(fill="both", expand=True)

        table_wrap.grid_rowconfigure(0, weight=1)
        table_wrap.grid_columnconfigure(0, weight=1)

        ybar = AutoScrollbar(table_wrap, orient="vertical", style="Thin.Vertical.TScrollbar")
        xbar = AutoScrollbar(table_wrap, orient="horizontal", style="Thin.Horizontal.TScrollbar")

        self.orders_side = ttk.Treeview(
            table_wrap,
            style="Dark.Treeview",
            columns=("dir", "cargo", "price"),
            show="headings",
            height=26,
            yscrollcommand=ybar.set,
            xscrollcommand=xbar.set,
            selectmode="browse",
        )
        self.orders_side.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        ybar.config(command=self.orders_side.yview)
        xbar.config(command=self.orders_side.xview)

        self.orders_side.heading("dir", text="Направление")
        self.orders_side.heading("cargo", text="Груз")
        self.orders_side.heading("price", text="Цена")

        self.orders_side.column("dir", width=320, minwidth=280, stretch=False)
        self.orders_side.column("cargo", width=220, minwidth=180, stretch=False)
        self.orders_side.column("price", width=90, minwidth=80, stretch=False)

        self.orders_side_map = {}  # item -> order_id (int/str)

        # клик по заявке справа синхронизирует выделение в основной таблице
        def on_select(_e=None):
            sel = self.orders_side.selection()
            if not sel:
                return
            sid = self.orders_side_map.get(sel[0])
            if sid is None:
                return
            for it, od in self.id_map.items():
                try:
                    if int(od[0]) == int(sid):
                        self.tree.selection_set(it)
                        self.tree.see(it)
                        break
                except Exception:
                    continue

        self.orders_side.bind("<<TreeviewSelect>>", on_select, add="+")

    def _sync_orders_side(self):
        """Перестраивает правую панель заявок из self.id_map (только UI)."""
        if not hasattr(self, "orders_side") or self.orders_side is None:
            return
        try:
            for it in self.orders_side.get_children():
                self.orders_side.delete(it)
        except Exception:
            return
        self.orders_side_map = {}

        # Стабильный порядок: как в основной таблице
        for main_item in self.tree.get_children():
            od = self.id_map.get(main_item)
            if not od:
                continue
            oid, direction, cargo, tonnage, _truck, _date, price, _info = od
            display_cargo = f"{cargo} {tonnage}т" if (cargo or tonnage) else ""
            price_txt = f"{price}$" if price else ""
            row = self.orders_side.insert("", "end", values=(direction, display_cargo, price_txt))
            self.orders_side_map[row] = oid

    # ================= Hidden offers storage (keeps logic; not shown) =================
    def build_offers_storage(self):
        """Создаёт невидимую таблицу откликов, чтобы не ломать логику (poll_offers и т.д.)."""
        hidden = tk.Frame(self.root, bg=BG_MAIN)
        # НЕ pack/grid — это хранилище, UI не показывает
        self._offers_hidden_frame = hidden

        self.offers = ttk.Treeview(
            hidden,
            style="Dark.Treeview",
            columns=("check", "company", "price"),
            show="headings",
            height=10,
            selectmode="extended",
        )
        self.offers.heading("check", text="")
        self.offers.heading("company", text="Компания")
        self.offers.heading("price", text="Цена")
        self.offers.column("check", width=44, minwidth=44, stretch=False)
        self.offers.column("company", width=260, minwidth=260, stretch=False)
        self.offers.column("price", width=120, minwidth=120, stretch=False)

        self.offers.bind("<Button-1>", self.on_offer_click)
        self.offers_map = {}


    # ================= Offers dialog window (show/hide) =================
    def toggle_offers_window(self):
        """Кнопка сверху: показать/скрыть большое окно с откликами + поиск."""
        if self.offers_win and self.offers_win.winfo_exists():
            self._close_offers_window()
        else:
            self._open_offers_window()

    def _open_offers_window(self):
        win = tk.Toplevel(self.root)
        win.title("Отклики")
        _set_window_icon(win)
        win.configure(bg=BG_MAIN)
        win.geometry("1200x720")
        win.minsize(980, 600)
        win.transient(self.root.winfo_toplevel())
        disable_tk_bell(win)

        # Верх: поиск
        top = tk.Frame(win, bg=BG_MAIN, padx=12, pady=10)
        top.pack(fill="x")

        tk.Label(top, text="Поиск:", bg=BG_MAIN, fg=FG_TEXT).pack(side="left")

        search = style_entry(tk.Entry(top))
        search.pack(side="left", fill="x", expand=True, padx=(8, 10))
        self.add_placeholder(search, self.offers_dialog_placeholder)

        # Таблица откликов
        wrap = tk.Frame(win, bg=BG_MAIN, padx=12, pady=(0, 12))
        wrap.pack(fill="both", expand=True)

        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)

        ybar = AutoScrollbar(wrap, orient="vertical", style="Thin.Vertical.TScrollbar")
        xbar = AutoScrollbar(wrap, orient="horizontal", style="Thin.Horizontal.TScrollbar")

        tree = ttk.Treeview(
            wrap,
            style="Dark.Treeview",
            columns=("company", "price", "contact", "direction"),
            show="headings",
            selectmode="extended",
            yscrollcommand=ybar.set,
            xscrollcommand=xbar.set,
        )

        tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        ybar.config(command=tree.yview)
        xbar.config(command=tree.xview)

        tree.heading("company", text="Компания")
        tree.heading("price", text="Цена")
        tree.heading("contact", text="Контакт")
        tree.heading("direction", text="Заявка / Направление")

        # Ширины: направление делаем широким (под длинные тексты)
        tree.column("company", width=240, minwidth=220, stretch=False)
        tree.column("price", width=110, minwidth=90, stretch=False)
        tree.column("contact", width=200, minwidth=160, stretch=False)
        tree.column("direction", width=620, minwidth=520, stretch=True)

        # Сохраняем ссылки
        self.offers_win = win
        self.offers_dialog_tree = tree
        self.offers_dialog_search = search
        self.offers_dialog_map = {}  # item -> (order_id, transport_user, off, direction)

        # Обновление вида по фильтру
        def _on_search(_e=None):
            self._refresh_offers_dialog_view()

        search.bind("<KeyRelease>", _on_search, add="+")
        search.bind("<Return>", _on_search, add="+")
        search.bind("<Escape>", lambda _e: self._close_offers_window(), add="+")

        # При закрытии крестиком — тоже "Скрыть"
        win.protocol("WM_DELETE_WINDOW", self._close_offers_window)

        # Заполняем текущими откликами из self.offers_map
        self._refresh_offers_dialog_view()

        # Обновим текст кнопки
        try:
            self.btn_toggle_offers.config(text="🙈 Скрыть отклики")
        except Exception:
            pass

    def _close_offers_window(self):
        try:
            if self.offers_win and self.offers_win.winfo_exists():
                self.offers_win.destroy()
        except Exception:
            pass
        self.offers_win = None
        self.offers_dialog_tree = None
        self.offers_dialog_map = {}
        self.offers_dialog_search = None
        try:
            self.btn_toggle_offers.config(text="👁 Показать отклики")
        except Exception:
            pass

    def _refresh_offers_dialog_view(self):
        """Перестраивает список откликов в диалоге с учетом строки поиска."""
        if not (self.offers_dialog_tree and self.offers_dialog_tree.winfo_exists()):
            return

        tree = self.offers_dialog_tree

        # filter text (без placeholder)
        f = ""
        if self.offers_dialog_search is not None:
            f = self.get_entry_value(self.offers_dialog_search)
        f_norm = (f or "").strip().lower()

        # Очистка
        for it in tree.get_children():
            tree.delete(it)
        self.offers_dialog_map = {}

        # Берем исходные данные из основной карты (она авторитетная)
        # self.offers_map: row_item -> (order_id, transport_user, off)
        for _item, meta in list(self.offers_map.items()):
            try:
                order_id, transport_user, off = meta
            except Exception:
                continue

            company = (off.get("company") or "").strip()
            price = off.get("price")
            contact = (off.get("contact") or "").strip()

            # Найдем направление по order_id
            direction = ""
            try:
                oid = int(order_id)
                for __it, od in self.id_map.items():
                    if int(od[0]) == oid:
                        direction = str(od[1] or "")
                        break
            except Exception:
                direction = ""

            blob = f"{company} {price} {contact} {direction}".lower()
            if f_norm and (f_norm not in blob):
                continue

            price_txt = f"{price}$" if (price not in (None, "", 0, 0.0)) else ""
            row = tree.insert("", "end", values=(company or "—", price_txt, contact or "—", direction or f"Заявка #{order_id}"))
            self.offers_dialog_map[row] = (order_id, transport_user, off, direction)

    def add_order(self):
        try:
            data = {}
            for label, entry in self.entries.items():
                # placeholder никогда не попадает в данные
                data[label] = self.get_entry_value(entry)

            required_fields = {
                "Откуда": data.get("Откуда", ""),
                "Куда": data.get("Куда", ""),
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

            direction = f"{data.get('Откуда', '').strip()} - {data.get('Куда', '').strip()}"
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

            # self._sync_orders_side()  # removed: single unified orders panel

            # корректный сброс полей обратно к подсказкам
            self.reset_left_fields()


        except Exception as e:
            error(self.root, "Ошибка", ("Проверьте поля заявки: некоторые значения заполнены неверно." + (f"\n\n[Тех. детали: {e}]" if SHOW_TECH_ERRORS else "")))

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
            error(self.root, "Ошибка", ("Не удалось загрузить заявки.\n\nПроверьте соединение и попробуйте ещё раз." + (f"\n\n[Тех. детали: {e}]" if SHOW_TECH_ERRORS else "")))
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

        # self._sync_orders_side()  # removed: single unified orders panel

        if initial_fetch and self.active_orders:
            self.start_polling()

    def on_order_check_click(self, event):
        # Запрещаем пользователю менять ширину колонок перетаскиванием разделителя
        try:
            region = self.tree.identify_region(event.x, event.y)
            if region == "separator":
                return "break"
        except Exception:
            pass

        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if col == "#1" and item:
            values = list(self.tree.item(item, "values"))
            values[0] = CHECKED if values[0] == UNCHECKED else UNCHECKED
            self.tree.item(item, values=values)
            return "break"


    def _block_tree_column_resize(self, event):
        # Доп. блокировка drag-ресайза колонок
        try:
            region = self.tree.identify_region(event.x, event.y)
            if region == "separator":
                return "break"
        except Exception:
            pass

    def _fit_orders_columns(self):
        """Растягивает колонки таблицы заявок на всю ширину панели.
        Ширины фиксируются (stretch=False), пользователь не может их менять.
        """
        if not hasattr(self, "tree") or self.tree is None:
            return

        try:
            total_w = int(self.tree.winfo_width())
        except Exception:
            return

        if total_w <= 50:
            return

        # фиксированная колонка чекбокса
        check_w = 44
        try:
            self.tree.column("check", width=check_w, minwidth=check_w, stretch=False)
        except Exception:
            pass

        usable = max(10, total_w - check_w - 4)  # небольшой запас
        weights = getattr(self, "_orders_col_weights", None) or {
            "dir": 0.34, "cargo": 0.24, "truck": 0.18, "price": 0.10, "info": 0.14
        }

        # нормализация весов
        s = sum(float(v) for v in weights.values()) or 1.0
        widths = {k: int(usable * float(v) / s) for k, v in weights.items()}

        # чтобы сумма была ровно usable
        diff = usable - sum(widths.values())
        if diff != 0:
            # добавим/уберем разницу в самую широкую колонку (обычно direction)
            key = max(widths, key=lambda k: widths[k])
            widths[key] = max(40, widths[key] + diff)

        # применяем
        for col, w in widths.items():
            w = max(60, int(w))
            try:
                self.tree.column(col, width=w, minwidth=w, stretch=False)
            except Exception:
                pass

    def save_and_run(self):
        if not self.id_map:
            return

        info(self.root, "Публикация", "Заявки загружены. Пожалуйста, ожидайте откликов.")

        first = True
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
                        error(self.root, "Ошибка", format_api_error(resp, "Не удалось отправить заявку. Попробуйте ещё раз."))
                except Exception as e:
                    error(self.root, "Ошибка", ("Не удалось отправить заявку.\n\nПроверьте соединение и попробуйте ещё раз." + (f"\n\n[Тех. детали: {e}]" if SHOW_TECH_ERRORS else "")))

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

            # если открыто окно откликов — обновим
            self._refresh_offers_dialog_view()

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
        """Показывает информацию по выбранным откликам.
        Если открыто окно откликов — берём выделение из него.
        Иначе пытаемся взять из скрытой таблицы (совместимость со старой логикой).
        """

        # ===== 1) Prefer offers dialog selection (premium UI: отклики показываются в диалоге) =====
        if self.offers_dialog_tree is not None and self.offers_dialog_tree.winfo_exists():
            sel = list(self.offers_dialog_tree.selection())
            if not sel:
                warn(self.root, "Ошибка", "Выберите отклики в окне откликов")
                return

            lines = []
            for it in sel:
                meta = self.offers_dialog_map.get(it)
                if not meta:
                    continue
                order_id, _transport_user, off, direction = meta
                company = off.get("company", "—")
                contact = off.get("contact", "—")
                price = off.get("price", "—")
                lines.append(
                    f"Заявка: #{order_id}\n"
                    f"Направление: {direction or '—'}\n"
                    f"Компания: {company}\n"
                    f"Номер тел: {contact}\n"
                    f"Цена: {price}$\n"
                )

            if not lines:
                warn(self.root, "Ошибка", "Не удалось прочитать выбранные отклики")
                return

            info(self.root, f"Отклики: {len(lines)} шт.", (("-" * 22) + "\n").join(lines) if len(lines) > 1 else lines[0])
            return

        # ===== 2) Fallback: hidden offers list (старые кнопки остаются рабочими) =====
        items = []
        for it in self.offers.get_children():
            vals = self.offers.item(it, "values") or ()
            if vals and len(vals) >= 1 and vals[0] == CHECKED:
                items.append(it)

        if not items:
            items = list(self.offers.selection())

        if not items:
            warn(self.root, "Ошибка", "Откройте окно откликов и выберите отклики")
            return

        def get_direction_by_order_id(order_id) -> str:
            try:
                oid = int(order_id)
            except Exception:
                return ""
            for _item, od in self.id_map.items():
                try:
                    if int(od[0]) == oid:
                        return str(od[1] or "")
                except Exception:
                    continue
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

        info(self.root, f"Отклики: {len(lines)} шт.", (("-" * 22) + "\n").join(lines) if len(lines) > 1 else lines[0])

    def delete_selected_offers(self):
        """Удаляет выбранные отклики (UI) и помечает их как скрытые (removed_offers).
        В премиум-дизайне отклики выбираются в диалоговом окне.
        """

        # ===== 1) Prefer offers dialog selection =====
        if self.offers_dialog_tree is not None and self.offers_dialog_tree.winfo_exists():
            sel = list(self.offers_dialog_tree.selection())
            if not sel:
                warn(self.root, "Ошибка", "Выберите отклики в окне откликов")
                return

            for it in sel:
                meta = self.offers_dialog_map.get(it)
                if not meta:
                    continue
                order_id, transport_user, _off, _direction = meta

                if order_id not in self.removed_offers:
                    self.removed_offers[order_id] = set()
                self.removed_offers[order_id].add(transport_user)

                try:
                    self.offers_dialog_tree.delete(it)
                except Exception:
                    pass
                self.offers_dialog_map.pop(it, None)

                # also remove from hidden offers list (if present)
                for off_item, (oid, tu, _o) in list(self.offers_map.items()):
                    if int(oid) == int(order_id) and tu == transport_user:
                        try:
                            self.offers.delete(off_item)
                        except Exception:
                            pass
                        self.offers_map.pop(off_item, None)

            # refresh (keeps filtering consistent)
            self._refresh_offers_dialog_view()
            return

        # ===== 2) Fallback: hidden offers list =====
        to_remove = []
        for item in self.offers.get_children():
            vals = self.offers.item(item, "values") or ()
            if vals and len(vals) >= 1 and vals[0] == CHECKED:
                to_remove.append(item)

        if not to_remove:
            to_remove = list(self.offers.selection())

        if not to_remove:
            warn(self.root, "Ошибка", "Откройте окно откликов и выберите отклики")
            return

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

        self._refresh_offers_dialog_view()

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
                error(self.root, "Ошибка", format_api_error(resp, "Не удалось закрыть выбранные заявки. Попробуйте ещё раз."))
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
    win.geometry("440x390")
    win.resizable(False, False)
    win.configure(bg=BG_MAIN)
    win.grab_set()
    disable_tk_bell(win)
    apply_global_font(win)
    _set_window_icon(win)

    panel = tk.Frame(win, bg=BG_PANEL, padx=20, pady=20, highlightthickness=1, highlightbackground=BORDER)
    panel.place(relx=0.5, rely=0.5, anchor="c", width=380, height=330)

    title = tk.Label(panel, text="Manager", bg=BG_PANEL, fg=ACCENT, font=(APP_FONT_FAMILY, 18, "bold"))
    title.pack(pady=(6, 8))

    form = tk.Frame(panel, bg=BG_PANEL)
    form.pack(fill="both", expand=True, padx=8, pady=(4, 10))

    def make_labeled_entry(parent, label: str, show: str = ""):
        lbl = tk.Label(parent, text=label, bg=BG_PANEL, fg=FG_TEXT)
        ent = style_entry(tk.Entry(parent, bg=ENTRY_BG, fg=ENTRY_FG, insertbackground="white", show=show))
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
                if isinstance(j, dict) and j.get("error") in (
                    "license_inactive", "license_expired", "license_not_found",
                    "license_app_mismatch", "device_limit_reached",
                ):
                    exit_app(win, "Ключ продукта недействителен")
                else:
                    error(win, "Ошибка", format_api_error(r, "Не удалось войти. Проверьте логин и пароль."))
                return

            data = r.json()
            if isinstance(data, dict) and data.get("license_valid") is False:
                exit_app(win, "Ключ продукта недействителен")
            token = data.get("token")
            role = (data.get("role") or "").lower()

            if role not in ("manager", "admin"):
                error(win, "Ошибка", "Непредвиденная ошибка")
                return

            if not token:
                error(win, "Ошибка", "Сервер не вернул токен")
                return

            if remember.get():
                try:
                    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                        f.write(token)
                except Exception:
                    pass

            result["token"] = token
            win.destroy()

        except Exception as e:
            error(win, "Ошибка", ("Не удалось подключиться к серверу.\n\nПроверьте интернет и попробуйте ещё раз." + (f"\n\n[Тех. детали: {e}]" if SHOW_TECH_ERRORS else "")))

    def open_register_window(parent_win: tk.Toplevel):
        reg = tk.Toplevel(parent_win)
        reg.title("Регистрация")
        reg.geometry("440x700")
        reg.resizable(False, False)
        reg.configure(bg=BG_MAIN)
        reg.grab_set()
        disable_tk_bell(reg)
        apply_global_font(reg)
        _set_window_icon(reg)

        panel2 = tk.Frame(reg, bg=BG_PANEL, highlightthickness=1, highlightbackground=BORDER)
        panel2.place(relx=0.5, rely=0.5, anchor="c", width=420, height=690)

        tk.Label(
            panel2,
            text="Регистрация аккаунта",
            bg=BG_PANEL,
            fg=FG_TEXT,
            font=(APP_FONT_FAMILY, 14, "bold"),
        ).pack(pady=(16, 10))

        phone_validator = reg.register(lambda value: value.isdigit() or value == "")

        def labeled(parent, label, show="", digits_only=False):
            tk.Label(parent, text=label, bg=BG_PANEL, fg=FG_TEXT).pack(anchor="w", padx=18, pady=(8, 2))
            e = style_entry(tk.Entry(parent, bg=ENTRY_BG, fg=ENTRY_FG, insertbackground="white", show=show))
            if digits_only:
                e.config(validate="key", validatecommand=(phone_validator, "%P"))
            e.pack(fill="x", padx=18)
            return e

        u_e = labeled(panel2, "Логин")
        p_e = labeled(panel2, "Пароль", show="*")
        email_e = labeled(panel2, "Почта (email)")
        phone_e = labeled(panel2, "Номер телефона", digits_only=True)
        company_e = labeled(panel2, "Название компании")
        key_e = labeled(panel2, "Ключ продукта")
        key2_e = labeled(panel2, "Подтверждение ключа")

        def do_register_real():
            u = u_e.get().strip()
            p = p_e.get().strip()
            email = email_e.get().strip()
            phone = phone_e.get().strip()
            company_name = company_e.get().strip()
            key = key_e.get().strip()
            key2 = key2_e.get().strip()

            if not u or not p or not email or not phone or not company_name or not key or not key2:
                error(reg, "Ошибка", "Заполните все поля")
                return

            if not phone.isdigit():
                error(reg, "Ошибка", "Номер телефона должен содержать только цифры")
                return

            if key != key2:
                error(reg, "Ошибка", "Ключ и подтверждение не совпадают")
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
                        "license_key_confirm": key2,
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
                    error(reg, "Ошибка", format_api_error(r, "Не удалось зарегистрироваться. Проверьте данные и попробуйте ещё раз."))
                    return

                info(reg, "Готово", "Аккаунт создан")
                reg.destroy()

                user_e.delete(0, tk.END)
                user_e.insert(0, u)
                pass_e.delete(0, tk.END)
                pass_e.focus_set()

            except Exception as e:
                error(reg, "Ошибка", ("Не удалось подключиться к серверу.\n\nПроверьте интернет и попробуйте ещё раз." + (f"\n\n[Тех. детали: {e}]" if SHOW_TECH_ERRORS else "")))

        modern_button(panel2, "Зарегистрироваться", do_register_real, variant="accent").pack(fill="x", padx=18, pady=(8, 10))

        reg.bind("<Return>", lambda _e: do_register_real())
        reg.bind("<Escape>", lambda _e: reg.destroy())
        u_e.focus_set()

    modern_button(panel, "Войти", do_login, variant="accent").pack(fill="x", padx=18, pady=(0, 8))
    modern_button(panel, "Регистрация", lambda: open_register_window(win), variant="secondary").pack(fill="x", padx=18, pady=(0, 12))

    win.bind("<Return>", lambda _e: do_login())
    user_e.focus_set()

    root.wait_window(win)
    return result["token"]
def try_restore_token() -> Optional[str]:
    p = TOKEN_FILE
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



