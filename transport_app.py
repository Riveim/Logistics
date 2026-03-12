# transport_app.py
# -*- coding: utf-8 -*-

import os
import json
import time
import uuid
import threading
import queue
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple

import tkinter as tk
from tkinter import ttk

import requests

from market_stats_popup import open_market_stats_popup

# ================== CONFIG ==================
LOGIN_ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "icon.ico")
SITE_LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "icon.png")
LOGIN_BG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "login_background.jpg")

API_URL = os.getenv("API_URL", "http://34.179.169.197")

POLL_INTERVAL_MS = 4000
HTTP_TIMEOUT = 8
MY_ANSWERS_WINDOW_HOURS = 48
MY_ANSWERS_WINDOW_SECONDS = MY_ANSWERS_WINDOW_HOURS * 3600

# ================== UI THEME ==================
# Match the Rivee website visual language
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

APP_FONT_FAMILY = os.getenv("APP_FONT_FAMILY", "Segoe UI Variable")
APP_FONT_SIZE = int(os.getenv("APP_FONT_SIZE", "11"))
APP_FONT = (APP_FONT_FAMILY, APP_FONT_SIZE)
APP_FONT_BOLD = (APP_FONT_FAMILY, APP_FONT_SIZE, "bold")

PH_PRICE = "Например: 1200"
PH_COMMENT = "Например: можем сегодня, оплата нал/перечисление"
PH_CONTACT = "+99890... или @username"
PH_COMPANY = "Например: TruckLine / Aziz"
TRANSPORT_TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transport_auth_token.txt")


def repair_mojibake_text(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value
    try:
        repaired = value.encode("cp1251").decode("utf-8")
        return repaired if repaired else value
    except Exception:
        return value


def repair_mojibake_obj(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: repair_mojibake_obj(v) for k, v in value.items()}
    if isinstance(value, list):
        return [repair_mojibake_obj(v) for v in value]
    return repair_mojibake_text(value)

def disable_tk_bell(widget: tk.Misc) -> None:
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


def apply_global_font(root: tk.Misc) -> None:
    try:
        root.option_add("*Font", APP_FONT)
    except Exception:
        pass


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
        disabled_fg: str = PLACEHOLDER_FG,
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

        self._rect_id = None
        self._text_id = None

        self.bind("<Configure>", lambda _e: self._redraw(), add="+")
        self.bind("<Button-1>", self._on_click, add="+")
        self.bind("<Enter>", self._on_enter, add="+")
        self.bind("<Leave>", self._on_leave, add="+")
        self._redraw()

    def _rounded_rect_points(self, x1, y1, x2, y2, r):
        r = min(r, int((x2 - x1) / 2), int((y2 - y1) / 2))
        return [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1
        ]

    def _ensure_size(self):
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

        fill = self._base_bg if self._state != "disabled" else BORDER
        pts = self._rounded_rect_points(1, 1, w - 1, h - 1, r)
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
        self._set_bg(self._active_bg)
        self.after(90, lambda: self._set_bg(self._hover_bg))
        try:
            if callable(self._command):
                self._command()
        except Exception:
            pass

    def config(self, **kwargs):
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

    def _on_resize(self, _e=None):
        w = max(1, self.winfo_width())
        h = max(1, self.winfo_height())
        self.delete("bg")
        r = min(self._radius, max(8, (min(w, h) // 2) - 2))
        pts = self._rounded_rect(2, 2, w-2, h-2, r)
        self.create_polygon(pts, smooth=True, splinesteps=18, fill=self._bg, outline=self._bg, tags="bg")
        self.coords(self._win_id, self._padding, self._padding)
        self.itemconfigure(self._win_id, width=max(1, w - self._padding*2), height=max(1, h - self._padding*2))


class AutoScrollbar(ttk.Scrollbar):
    def set(self, lo, hi):
        lo = float(lo)
        hi = float(hi)
        if lo <= 0.0 and hi >= 1.0:
            self.grid_remove()
        else:
            self.grid()
        super().set(lo, hi)

    def pack(self, *args, **kwargs):
        raise tk.TclError("Use grid() with AutoScrollbar")

    def place(self, *args, **kwargs):
        raise tk.TclError("Use grid() with AutoScrollbar")


def _set_window_icon(win: tk.Toplevel) -> None:
    try:
        if LOGIN_ICON_PATH and os.path.exists(LOGIN_ICON_PATH):
            win.iconbitmap(LOGIN_ICON_PATH)
    except Exception:
        pass


def dark_message(parent: tk.Misc, title: str, text: str, kind: str = "info") -> None:
    """
    kind: info | warning | error
    Premium rounded dialog (rounded container + rounded button) like manager_app.
    """
    win = tk.Toplevel(parent)
    win.title(title)
    _set_window_icon(win)
    win.configure(bg=BG_MAIN)

    win.transient(parent.winfo_toplevel())
    win.grab_set()
    disable_tk_bell(win)

    win.update_idletasks()
    screen_w = win.winfo_screenwidth()
    screen_h = win.winfo_screenheight()

    max_text_w = min(760, int(screen_w * 0.70))
    min_win_w = 420
    min_win_h = 190

    card = RoundedCard(win, bg=BG_PANEL, radius=18, padding=18)
    card.pack(fill="both", expand=True, padx=16, pady=16)

    msg = tk.Label(
        card.inner,
        text=text,
        bg=BG_PANEL,
        fg=FG_TEXT,
        justify="left",
        anchor="nw",
        wraplength=max_text_w,
        font=APP_FONT,
    )
    msg.pack(fill="both", expand=True)

    footer = tk.Frame(card.inner, bg=BG_PANEL)
    footer.pack(fill="x", pady=(14, 0))

    def close():
        try:
            win.grab_release()
        except Exception:
            pass
        win.destroy()

    variant = "accent"
    if kind == "warning":
        variant = "warn"
    elif kind == "error":
        variant = "danger"

    ok_btn = modern_button(footer, "OK", close, variant=variant)
    ok_btn.pack(side="right")

    win.bind("<Escape>", lambda _e: close())
    win.bind("<Return>", lambda _e: close())

    win.update_idletasks()
    req_w = max(min_win_w, win.winfo_reqwidth())
    req_h = max(min_win_h, win.winfo_reqheight())

    req_w = min(req_w, int(screen_w * 0.85))
    req_h = min(req_h, int(screen_h * 0.85))

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
    win.lift()
    try:
        ok_btn.focus_set()
    except Exception:
        pass
    parent.winfo_toplevel().wait_window(win)

def info(parent: tk.Misc, title: str, text: str) -> None:
    dark_message(parent, title, text, "info")


def warn(parent: tk.Misc, title: str, text: str) -> None:
    dark_message(parent, title, text, "warning")


def error(parent: tk.Misc, title: str, text: str) -> None:
    dark_message(parent, title, text, "error")


def get_device_id() -> str:
    return str(uuid.getnode())


PROFILE_PATH = "transport_profiles.json"


def _load_profiles() -> Dict[str, Dict[str, str]]:
    try:
        with open(PROFILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_profile(username: str, phone: str, company: str = "", frozen: bool = False) -> None:
    username = (username or "").strip()
    if not username:
        return
    profiles = _load_profiles()
    profiles[username] = {
        "phone": (phone or "").strip(),
        "company": (company or "").strip(),
        "frozen": bool(frozen),
    }
    try:
        with open(PROFILE_PATH, "w", encoding="utf-8") as f:
            json.dump(profiles, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def safe_json(resp: requests.Response) -> Dict[str, Any]:
    try:
        return resp.json()
    except Exception:
        return {}


class LicenseKick(Exception):
    pass



def api_get_me(token: str) -> Dict[str, Any]:
    token = (token or '').strip()
    if not token:
        return {}
    try:
        r = requests.get(f"{API_URL}/me", headers={"Authorization": f"Bearer {token}"}, timeout=HTTP_TIMEOUT)
        if r.status_code == 200:
            j = safe_json(r)
            return j if isinstance(j, dict) else {}
        return {}
    except Exception:
        return {}


def load_login_image(path: str):
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


@dataclass
class IncomingOrder:
    id: int
    direction: str
    cargo: str
    tonnage: float
    truck: str
    date: str
    budget_price: float
    info: str
    from_company: str = ""


class TransportApp:
    def __init__(self, root: tk.Tk, token: str, username: str = ""):
        self.root = root
        apply_global_font(self.root)
        disable_tk_bell(self.root)

        self.token = token
        self.headers = {"Authorization": f"Bearer {token}"}

        self.http = requests.Session()
        self.http.headers.update(self.headers)

        # Wrap all HTTP requests: if server says the license is disabled/expired, force-exit the app.
        _orig_request = self.http.request

        def _wrapped_request(method, url, **kwargs):
            resp = _orig_request(method, url, **kwargs)
            try:
                j = safe_json(resp)
                if resp.status_code in (401, 403) and isinstance(j, dict) and j.get("error") in ("license_inactive", "license_expired"):
                    raise LicenseKick(j.get("error"))
            except LicenseKick:
                raise
            except Exception:
                pass
            return resp

        self.http.request = _wrapped_request

        # Профиль (телефон/компания) для автозаполнения оффера
        self.profile_username = (username or "").strip()
        prof = _load_profiles().get(self.profile_username, {}) if self.profile_username else {}
        prof = _load_profiles().get(self.profile_username, {}) if self.profile_username else {}
        self.profile_phone = (prof.get("phone") or "").strip()
        self.profile_company = (prof.get("company") or self.profile_username or "").strip()
        self.profile_frozen = bool(prof.get("frozen", False))

        # Если профиля нет (например, после обновления) — пробуем подтянуть телефон с сервера (/me)
        if not self.profile_phone:
            try:
                meta = api_get_me(self.token)
                phone = (meta.get('phone') or '').strip() if isinstance(meta, dict) else ''
                company = (meta.get('company_name') or '').strip() if isinstance(meta, dict) else ''
                if phone:
                    self.profile_phone = phone
                if company:
                    self.profile_company = company
                if self.profile_username and self.profile_phone:
                    _save_profile(self.profile_username, self.profile_phone, self.profile_company)
            except Exception:
                pass

        self.ui_queue = queue.Queue()
        self.root.after(50, self._process_ui_queue)

        self.polling_active = False
        self.auto_refresh_enabled = True
        self.orders_by_item: Dict[str, IncomingOrder] = {}
        self.sent_offers: Dict[int, Dict[str, Any]] = {}

        self._load_local_offers()

        self.my_answers_win = None
        self.my_answers_tree = None
        self.my_answers_search = None
        self.my_answers_details = None
        self.my_answers_records = []
        self.my_answers_map: Dict[str, Dict[str, Any]] = {}
        self.my_answers_focus_order_id: Optional[int] = None
        self.my_answers_placeholder = "Поиск: направление, заявка, цена, компания"

        root.title("Transport Manager — Входящие заявки")
        root.geometry("1400x780")
        root.configure(bg=BG_MAIN)
        maximize_window(root)

        self._init_styles()

        self._build_brand_header()
        self._build_left_panel()
        self._build_center_panel()

        self._update_profile_labels()
        self._refresh_incoming_orders(initial=True)
        self._start_polling()

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

    def _run_http_async(self, work_fn, on_ok=None, on_err=None):
        def _runner():
            try:
                result = work_fn()
                if on_ok:
                    self.ui_queue.put(lambda: on_ok(result))
            except LicenseKick as e:
                # Show message and exit immediately
                self.ui_queue.put(lambda: error(self.root, "Доступ отключён", "Доступ ограничен (ключ продукта истёк)"))
                self.ui_queue.put(lambda: self.root.after(200, lambda: os._exit(0)))
            except Exception as e:
                if on_err:
                    self.ui_queue.put(lambda: on_err(e))
                else:
                    self.ui_queue.put(lambda: error(self.root, "Ошибка", str(e)))

        threading.Thread(target=_runner, daemon=True).start()

    def _init_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("default")
        except Exception:
            pass

        # Global ttk defaults
        try:
            style.configure(".", font=APP_FONT)
            style.configure("TFrame", background=BG_MAIN)
            style.configure("TLabel", background=BG_PANEL, foreground=FG_TEXT, font=APP_FONT)
        except Exception:
            pass

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
        try:
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
        except Exception:
            pass


    def _add_placeholder(self, entry: tk.Entry, text: str):
        entry.delete(0, tk.END)
        entry.insert(0, text)
        entry.config(fg=PLACEHOLDER_FG)

        def on_focus_in(_):
            if entry.get() == text:
                entry.delete(0, tk.END)
                entry.config(fg=ENTRY_FG)

        def on_focus_out(_):
            if not entry.get():
                entry.insert(0, text)
                entry.config(fg=PLACEHOLDER_FG)

        entry.bind("<FocusIn>", on_focus_in)
        entry.bind("<FocusOut>", on_focus_out)

    def _offers_path(self) -> str:
        return "transport_sent_offers.json"

    def _load_local_offers(self):
        p = self._offers_path()
        if not os.path.exists(p):
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = repair_mojibake_obj(json.load(f))
            if isinstance(data, dict):
                self.sent_offers = {int(k): v for k, v in data.items()}
        except Exception:
            self.sent_offers = {}

    def _save_local_offers(self):
        try:
            with open(self._offers_path(), "w", encoding="utf-8") as f:
                json.dump(self.sent_offers, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("save offers failed:", e)

    def _build_brand_header(self):
        top = tk.Frame(self.root, bg=BG_PANEL, padx=18, pady=14, highlightthickness=1, highlightbackground=BORDER)
        top.pack(fill="x", padx=16, pady=(14, 10))

        brand = tk.Frame(top, bg=BG_PANEL)
        brand.pack(side="left")

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

        tk.Label(
            top,
            text="Рынок заявок и офферов",
            bg=BG_PANEL,
            fg=FG_MUTED,
            font=APP_FONT,
        ).pack(side="left", padx=(18, 0))

        modern_button(top, "Выйти", self._logout, variant="danger").pack(side="right")
        self.btn_my_answers = modern_button(
            top,
            "Мои ответы",
            self.toggle_my_answers_window,
            variant="default",
        )
        self.btn_my_answers.pack(side="right", padx=(0, 8))

    def _logout(self):
        try:
            self._stop_polling()
        except Exception:
            pass

        try:
            popup = getattr(self.root, "_market_stats_popup", None)
            if popup is not None:
                popup.close()
        except Exception:
            pass

        try:
            if getattr(self, "my_answers_win", None) is not None and self.my_answers_win.winfo_exists():
                self.my_answers_win.destroy()
        except Exception:
            pass
        try:
            if os.path.exists(TRANSPORT_TOKEN_FILE):
                os.remove(TRANSPORT_TOKEN_FILE)
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

        token, username = login_to_server(self.root)
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
        self.root._app = TransportApp(self.root, token, username=username)  # type: ignore[attr-defined]

    def _build_left_panel(self):
        left = tk.Frame(self.root, bg=BG_PANEL, padx=12, pady=12, highlightthickness=1, highlightbackground=BORDER)
        left.pack(side="left", fill="y", padx=(16, 0), pady=(0, 16))

        tk.Label(left, text="Оффер по выбранной заявке", bg=BG_PANEL, fg=FG_TEXT, font=APP_FONT_BOLD).pack(
            anchor="w", pady=(0, 10)
        )

        tk.Label(left, text="Цена (обязательно)", bg=BG_PANEL, fg=FG_TEXT).pack(anchor="w")
        self.price_e = style_entry(tk.Entry(left, bg=ENTRY_BG, fg=ENTRY_FG, insertbackground="white", width=35))
        self.price_e.pack(pady=4)
        self._add_placeholder(self.price_e, PH_PRICE)

        tk.Label(left, text="Комментарий (необязательно)", bg=BG_PANEL, fg=FG_TEXT).pack(anchor="w")
        self.comment_e = style_entry(tk.Entry(left, bg=ENTRY_BG, fg=ENTRY_FG, insertbackground="white", width=35))
        self.comment_e.pack(pady=4)
        self._add_placeholder(self.comment_e, PH_COMMENT)

        tk.Label(left, text="Телефон (для контакта)", bg=BG_PANEL, fg=FG_TEXT).pack(anchor="w", pady=(10, 0))
        self.contact_var = tk.StringVar(value=self.profile_phone or "")
        self.contact_e2 = style_entry(tk.Entry(left, textvariable=self.contact_var, bg=ENTRY_BG, fg=ENTRY_FG,
                                   insertbackground="white", width=35))
        self.contact_e2.pack(pady=4)

        tk.Label(left, text="Компания", bg=BG_PANEL, fg=FG_TEXT).pack(anchor="w")
        self.company_var = tk.StringVar(value=self.profile_company or "")
        self.company_e2 = style_entry(tk.Entry(left, textvariable=self.company_var, bg=ENTRY_BG, fg=ENTRY_FG,
                                   insertbackground="white", width=35))
        self.company_e2.pack(pady=4)

        self.freeze_var = tk.BooleanVar(value=getattr(self, "profile_frozen", False))

        def apply_freeze_state():
            frozen = self.freeze_var.get()
            self.contact_e2.config(state=("disabled" if frozen else "normal"))
            self.company_e2.config(state=("disabled" if frozen else "normal"))

            # если заморозили — сохраняем текущие значения
            if self.profile_username:
                _save_profile(
                    self.profile_username,
                    self.contact_var.get().strip(),
                    self.company_var.get().strip(),
                    frozen=frozen
                )

        tk.Checkbutton(
            left,
            text="🔒 Заморозить телефон и компанию",
            variable=self.freeze_var,
            command=apply_freeze_state,
            bg=BG_PANEL,
            fg=FG_TEXT,
            selectcolor=BG_PANEL,
            activebackground=BG_PANEL,
            activeforeground=FG_TEXT,
        ).pack(anchor="w", pady=(4, 0))

        apply_freeze_state()

        modern_button(left, "📨 Отправить оффер", self._send_offer, variant="accent").pack(pady=10, fill="x")

        modern_button(left, "🧹 Очистить поля", self._clear_offer_fields, variant="secondary").pack(pady=5, fill="x")
        modern_button(left, "📊 Статистика", self._open_market_stats_window, variant="default").pack(pady=5, fill="x")

        tk.Label(left, text="Статус:", bg=BG_PANEL, fg=FG_TEXT).pack(anchor="w", pady=(20, 0))
        self.status_lbl = tk.Label(left, text="—", bg=BG_PANEL, fg=FG_TEXT)
        self.status_lbl.pack(anchor="w")

        self.auto_btn = RoundedButton(left, text="⏸ Авто-обновление: ВКЛ", command=self._toggle_auto_refresh, bg=BTN_SUCCESS, fg="white", hover_bg=BTN_SUCCESS, active_bg=ACCENT, radius=14, padx=16, pady=9, font=APP_FONT_BOLD)
        self.auto_btn.pack(fill="x", pady=(10, 0))

    def _open_market_stats_window(self):
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

    def _build_center_panel(self):
        center = tk.Frame(self.root, bg=BG_MAIN)
        center.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        table_wrap = tk.Frame(center, bg=BG_MAIN)
        table_wrap.pack(fill="both", expand=True)

        table_wrap.grid_rowconfigure(0, weight=1)
        table_wrap.grid_columnconfigure(0, weight=1)

        ybar = AutoScrollbar(table_wrap, orient="vertical", style="Thin.Vertical.TScrollbar")
        xbar = AutoScrollbar(table_wrap, orient="horizontal", style="Thin.Horizontal.TScrollbar")

        self.tree = ttk.Treeview(
            table_wrap,
            style="Dark.Treeview",
            columns=("check", "id", "dir", "cargo", "truck", "date", "budget", "info", "my_offer"),
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

        self.tree.heading("check", text="")
        self.tree.heading("id", text="ID")
        self.tree.heading("dir", text="Направление")
        self.tree.heading("cargo", text="Груз")
        self.tree.heading("truck", text="Транспорт")
        self.tree.heading("date", text="Дата")
        self.tree.heading("budget", text="Бюджет")
        self.tree.heading("info", text="Требования")
        self.tree.heading("my_offer", text="Мой оффер")

        self.tree.column("check", width=44, minwidth=44, stretch=False)
        self.tree.column("id", width=70, minwidth=70, stretch=False)
        self.tree.column("dir", width=260, minwidth=260, stretch=False)
        self.tree.column("cargo", width=240, minwidth=240, stretch=False)
        self.tree.column("truck", width=180, minwidth=180, stretch=False)
        self.tree.column("date", width=120, minwidth=120, stretch=False)
        self.tree.column("budget", width=110, minwidth=110, stretch=False)
        self.tree.column("info", width=280, minwidth=280, stretch=False)
        self.tree.column("my_offer", width=120, minwidth=120, stretch=False)

        self.tree.bind("<Button-1>", self.on_order_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_select_order)

    def _snapshot_order(self, order: IncomingOrder) -> Dict[str, Any]:
        return {
            "id": order.id,
            "direction": order.direction,
            "cargo": order.cargo,
            "tonnage": order.tonnage,
            "truck": order.truck,
            "date": order.date,
            "budget_price": order.budget_price,
            "info": order.info,
            "from_company": order.from_company,
            "market_status": "open",
        }

    def _format_number(self, value: Any) -> str:
        if value in (None, ""):
            return ""
        try:
            number = float(value)
        except Exception:
            return str(value)
        if number.is_integer():
            return str(int(number))
        return f"{number:.2f}".rstrip("0").rstrip(".")

    def _format_money(self, value: Any) -> str:
        text_value = self._format_number(value)
        return f"{text_value}$" if text_value else ""

    def _format_offer_ts(self, value: Any) -> str:
        if value in (None, ""):
            return ""
        try:
            if isinstance(value, str):
                stripped = value.strip()
                if not stripped:
                    return ""
                if stripped.isdigit():
                    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(stripped)))
                return stripped
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(float(value))))
        except Exception:
            return str(value)

    def _parse_sort_ts(self, value: Any) -> int:
        if value in (None, ""):
            return 0
        try:
            if isinstance(value, str):
                stripped = value.strip()
                if not stripped:
                    return 0
                if stripped.isdigit():
                    return int(stripped)
                return int(time.mktime(time.strptime(stripped, "%Y-%m-%d %H:%M:%S")))
            return int(float(value))
        except Exception:
            return 0

    def _my_answers_cutoff_ts(self) -> int:
        return int(time.time()) - MY_ANSWERS_WINDOW_SECONDS

    def _is_recent_my_answer_record(self, record: Dict[str, Any]) -> bool:
        sort_ts = self._parse_sort_ts(record.get("_sort_ts"))
        return sort_ts >= self._my_answers_cutoff_ts() if sort_ts else False

    def _display_order_status(self, value: Any) -> str:
        raw = str(value or "").strip().lower()
        if raw == "open":
            return "Открыта"
        if raw == "closed":
            return "Закрыта"
        return str(value or "")

    def _format_cargo_summary(self, cargo: Any, tonnage: Any) -> str:
        parts = []
        cargo_text = str(cargo or "").strip()
        tonnage_text = self._format_number(tonnage)
        if cargo_text:
            parts.append(cargo_text)
        if tonnage_text:
            parts.append(f"{tonnage_text}т")
        return " ".join(parts) or "—"

    def _normalize_my_answer_record(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        offer_ts_raw = raw.get("offer_created_at")
        if offer_ts_raw in (None, ""):
            offer_ts_raw = raw.get("ts")
        market_status = raw.get("market_status") or raw.get("order_status") or raw.get("status") or ""
        try:
            order_id = int(raw.get("order_id") or raw.get("id") or 0)
        except Exception:
            order_id = 0
        return {
            "order_id": order_id,
            "direction": str(repair_mojibake_text(raw.get("direction") or "")),
            "cargo": str(repair_mojibake_text(raw.get("cargo") or "")),
            "tonnage": raw.get("tonnage") or 0,
            "truck": str(repair_mojibake_text(raw.get("truck") or "")),
            "date": str(repair_mojibake_text(raw.get("date") or "")),
            "budget_price": raw.get("order_price") if raw.get("order_price") not in (None, "") else raw.get("budget_price"),
            "info": str(repair_mojibake_text(raw.get("info") or "")),
            "from_company": str(repair_mojibake_text(raw.get("from_company") or "")),
            "manager_username": str(repair_mojibake_text(raw.get("manager_username") or "")),
            "order_status": self._display_order_status(raw.get("order_status") or ""),
            "market_status": self._display_order_status(market_status),
            "offer_price": raw.get("offer_price") if raw.get("offer_price") not in (None, "") else raw.get("price"),
            "offer_comment": str(repair_mojibake_text(raw.get("offer_comment") or raw.get("comment") or "")),
            "offer_contact": str(repair_mojibake_text(raw.get("offer_contact") or raw.get("contact") or "")),
            "offer_company": str(repair_mojibake_text(raw.get("offer_company") or raw.get("company") or "")),
            "offer_ts": self._format_offer_ts(offer_ts_raw),
            "_sort_ts": self._parse_sort_ts(offer_ts_raw),
        }

    def _build_local_my_answer_records(self):
        current_orders = {order.id: order for order in self.orders_by_item.values()}
        records = []
        for order_id, data in self.sent_offers.items():
            if not isinstance(data, dict):
                continue
            offer_username = str(data.get("transport_username") or "").strip()
            if offer_username and self.profile_username and offer_username != self.profile_username:
                continue
            snapshot = data.get("order") if isinstance(data.get("order"), dict) else {}
            live_order = current_orders.get(order_id)
            raw = {
                "order_id": order_id,
                "direction": snapshot.get("direction") or (live_order.direction if live_order else ""),
                "cargo": snapshot.get("cargo") or (live_order.cargo if live_order else ""),
                "tonnage": snapshot.get("tonnage") if snapshot.get("tonnage") not in (None, "") else (live_order.tonnage if live_order else 0),
                "truck": snapshot.get("truck") or (live_order.truck if live_order else ""),
                "date": snapshot.get("date") or (live_order.date if live_order else ""),
                "budget_price": snapshot.get("budget_price") if snapshot.get("budget_price") not in (None, "") else (live_order.budget_price if live_order else ""),
                "info": snapshot.get("info") or (live_order.info if live_order else ""),
                "from_company": snapshot.get("from_company") or (live_order.from_company if live_order else ""),
                "market_status": snapshot.get("market_status") or ("open" if live_order else ""),
                "offer_price": data.get("price"),
                "offer_comment": data.get("comment"),
                "offer_contact": data.get("contact"),
                "offer_company": data.get("company"),
                "offer_created_at": data.get("offer_created_at") or data.get("ts"),
            }
            record = self._normalize_my_answer_record(raw)
            if self._is_recent_my_answer_record(record):
                records.append(record)
        records.sort(key=lambda item: item.get("_sort_ts", 0), reverse=True)
        return records

    def _format_my_answer_brief(self, record: Dict[str, Any]) -> str:
        parts = []
        price_text = self._format_money(record.get("offer_price"))
        if price_text:
            parts.append(price_text)
        company_text = str(record.get("offer_company") or "").strip()
        if company_text:
            parts.append(company_text)
        comment_text = str(record.get("offer_comment") or "").strip()
        if comment_text:
            parts.append(comment_text[:40] + ("..." if len(comment_text) > 40 else ""))
        return " / ".join(parts) or "—"

    def _format_my_answer_text(self, record: Dict[str, Any]) -> str:
        budget_text = self._format_money(record.get("budget_price")) or "—"
        offer_price_text = self._format_money(record.get("offer_price")) or "—"
        manager_text = record.get("from_company") or record.get("manager_username") or "—"
        lines = [
            f"Заявка: #{record.get('order_id')}",
            f"Направление: {record.get('direction') or '—'}",
            f"Груз: {self._format_cargo_summary(record.get('cargo'), record.get('tonnage'))}",
            f"Транспорт: {record.get('truck') or '—'}",
            f"Дата: {record.get('date') or '—'}",
            f"Бюджет заявки: {budget_text}",
            f"Требования: {record.get('info') or '—'}",
            f"Логист: {manager_text}",
        ]
        status_text = record.get("market_status") or record.get("order_status") or ""
        if status_text:
            lines.append(f"Статус заявки: {status_text}")
        lines.extend([
            "",
            "--- МОЙ ОТВЕТ ---",
            f"Когда отправлен: {record.get('offer_ts') or '—'}",
            f"Цена: {offer_price_text}",
            f"Контакт: {record.get('offer_contact') or '—'}",
            f"Компания: {record.get('offer_company') or '—'}",
            f"Комментарий: {record.get('offer_comment') or '—'}",
        ])
        return "\n".join(lines)

    def _set_my_answer_details(self, text: str):
        widget = self.my_answers_details
        if widget is None or not widget.winfo_exists():
            return
        widget.config(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, text)
        widget.config(state="disabled")

    def _copy_my_answer_details(self):
        widget = self.my_answers_details
        if widget is None or not widget.winfo_exists():
            return
        data = widget.get("1.0", tk.END).strip()
        if not data:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(data)
        info(self.root, "Готово", "Детали ответа скопированы в буфер обмена")

    def _show_selected_my_answer(self, _event=None):
        tree = self.my_answers_tree
        if tree is None or not tree.winfo_exists():
            return
        sel = tree.selection()
        if not sel:
            self._set_my_answer_details("Выберите ответ в списке.")
            return
        record = self.my_answers_map.get(sel[0])
        if not record:
            self._set_my_answer_details("Не удалось прочитать детали ответа.")
            return
        self._set_my_answer_details(self._format_my_answer_text(record))

    def _refresh_my_answers_view(self):
        tree = self.my_answers_tree
        if tree is None or not tree.winfo_exists():
            return

        current_order_id = None
        current_sel = tree.selection()
        if current_sel:
            current_record = self.my_answers_map.get(current_sel[0])
            if current_record:
                current_order_id = current_record.get("order_id")
        if current_order_id is None and self.my_answers_focus_order_id is not None:
            current_order_id = self.my_answers_focus_order_id

        search_text = ""
        if self.my_answers_search is not None and self.my_answers_search.winfo_exists():
            raw = self.my_answers_search.get().strip()
            if raw != self.my_answers_placeholder:
                search_text = raw.lower()

        for item in tree.get_children():
            tree.delete(item)
        self.my_answers_map = {}

        selected_item = None
        first_item = None
        for record in self.my_answers_records:
            haystack = " ".join([
                str(record.get("order_id") or ""),
                str(record.get("direction") or ""),
                str(record.get("cargo") or ""),
                str(record.get("offer_company") or ""),
                str(record.get("offer_comment") or ""),
                str(record.get("offer_contact") or ""),
                str(record.get("offer_ts") or ""),
            ]).lower()
            if search_text and search_text not in haystack:
                continue

            item = tree.insert(
                "",
                "end",
                values=(
                    record.get("offer_ts") or "—",
                    f"#{record.get('order_id')}",
                    record.get("direction") or "—",
                    self._format_my_answer_brief(record),
                ),
            )
            self.my_answers_map[item] = record
            if first_item is None:
                first_item = item
            if current_order_id is not None and record.get("order_id") == current_order_id:
                selected_item = item

        target_item = selected_item or first_item
        if target_item is not None:
            tree.selection_set(target_item)
            tree.focus(target_item)
            tree.see(target_item)
            self._show_selected_my_answer()
        else:
            self._set_my_answer_details(f"Ответы за последние {MY_ANSWERS_WINDOW_HOURS} часов не найдены.")
        self.my_answers_focus_order_id = None

    def _load_my_answers(self):
        self._set_my_answer_details("Загрузка истории ответов...")

        def work():
            try:
                resp = self.http.get(
                    f"{API_URL}/market/my-offers",
                    params={"hours": MY_ANSWERS_WINDOW_HOURS},
                    timeout=HTTP_TIMEOUT,
                )
                return ("remote", resp)
            except Exception:
                return ("local", None)

        def on_ok(result):
            source, resp = result
            local_records = self._build_local_my_answer_records()
            records_map = {record.get("order_id"): dict(record) for record in local_records if record.get("order_id")}
            extra_records = [dict(record) for record in local_records if not record.get("order_id")]

            if source == "remote" and resp is not None:
                if resp.status_code == 200:
                    payload = safe_json(resp)
                    items = payload.get("items") if isinstance(payload, dict) else payload
                    if isinstance(items, list):
                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            record = self._normalize_my_answer_record(item)
                            order_id = record.get("order_id")
                            if order_id:
                                merged = dict(records_map.get(order_id, {}))
                                for key, value in record.items():
                                    if value is None:
                                        continue
                                    if isinstance(value, str) and not value.strip():
                                        continue
                                    if isinstance(value, (list, dict)) and not value:
                                        continue
                                    merged[key] = value
                                records_map[order_id] = merged
                            else:
                                extra_records.append(record)
                elif resp.status_code == 401:
                    error(self.root, "Сессия", "Токен недействителен. Нужно войти заново.")
                    self._stop_polling()
                    return

            records = [
                record
                for record in (list(records_map.values()) + extra_records)
                if self._is_recent_my_answer_record(record)
            ]
            records.sort(key=lambda item: item.get("_sort_ts", 0), reverse=True)
            self.my_answers_records = records
            self._refresh_my_answers_view()
        self._run_http_async(work, on_ok=on_ok)

    def toggle_my_answers_window(self):
        if self.my_answers_win and self.my_answers_win.winfo_exists():
            self._close_my_answers_window()
        else:
            order = self._selected_order()
            if order and self.sent_offers.get(order.id):
                self.my_answers_focus_order_id = int(order.id)
            else:
                self.my_answers_focus_order_id = None
            self._open_my_answers_window()

    def _open_my_answers_window(self):
        win = tk.Toplevel(self.root)
        win.title("Мои ответы")
        _set_window_icon(win)
        win.configure(bg=BG_MAIN)
        win.geometry("1280x760")
        win.minsize(1040, 620)
        win.transient(self.root.winfo_toplevel())
        disable_tk_bell(win)

        top = tk.Frame(win, bg=BG_MAIN, padx=12, pady=10)
        top.pack(fill="x")

        tk.Label(top, text="Поиск:", bg=BG_MAIN, fg=FG_TEXT).pack(side="left")
        search = style_entry(tk.Entry(top))
        search.pack(side="left", fill="x", expand=True, padx=(8, 10))
        self._add_placeholder(search, self.my_answers_placeholder)
        modern_button(top, "Обновить", self._load_my_answers, variant="secondary").pack(side="left")

        body = tk.Frame(win, bg=BG_MAIN, padx=12, pady=(0, 12))
        body.pack(fill="both", expand=True)

        left = tk.Frame(body, bg=BG_MAIN)
        left.pack(side="left", fill="both", expand=True)

        right = tk.Frame(body, bg=BG_PANEL, padx=12, pady=12, highlightthickness=1, highlightbackground=BORDER)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))

        table_wrap = tk.Frame(left, bg=BG_MAIN)
        table_wrap.pack(fill="both", expand=True)
        table_wrap.grid_rowconfigure(0, weight=1)
        table_wrap.grid_columnconfigure(0, weight=1)

        ybar = AutoScrollbar(table_wrap, orient="vertical", style="Thin.Vertical.TScrollbar")
        xbar = AutoScrollbar(table_wrap, orient="horizontal", style="Thin.Horizontal.TScrollbar")

        tree = ttk.Treeview(
            table_wrap,
            style="Dark.Treeview",
            columns=("when", "order", "direction", "offer"),
            show="headings",
            selectmode="browse",
            yscrollcommand=ybar.set,
            xscrollcommand=xbar.set,
        )
        tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        ybar.config(command=tree.yview)
        xbar.config(command=tree.xview)

        tree.heading("when", text="Когда")
        tree.heading("order", text="Заявка")
        tree.heading("direction", text="Направление")
        tree.heading("offer", text="Мой ответ")

        tree.column("when", width=170, minwidth=150, stretch=False)
        tree.column("order", width=90, minwidth=80, stretch=False)
        tree.column("direction", width=360, minwidth=280, stretch=True)
        tree.column("offer", width=320, minwidth=260, stretch=True)

        tk.Label(right, text="Заявка и мой ответ", bg=BG_PANEL, fg=FG_TEXT, font=APP_FONT_BOLD).pack(anchor="w", pady=(0, 8))

        details_wrap = tk.Frame(right, bg=BG_PANEL)
        details_wrap.pack(fill="both", expand=True)
        details_wrap.grid_rowconfigure(0, weight=1)
        details_wrap.grid_columnconfigure(0, weight=1)

        details_ybar = AutoScrollbar(details_wrap, orient="vertical", style="Thin.Vertical.TScrollbar")
        details = tk.Text(
            details_wrap,
            bg=ENTRY_BG,
            fg=FG_TEXT,
            insertbackground="white",
            wrap="word",
            yscrollcommand=details_ybar.set,
        )
        details.grid(row=0, column=0, sticky="nsew")
        details_ybar.grid(row=0, column=1, sticky="ns")
        details_ybar.config(command=details.yview)

        modern_button(right, "Копировать детали", self._copy_my_answer_details, variant="accent").pack(fill="x", pady=(10, 0))

        self.my_answers_win = win
        self.my_answers_tree = tree
        self.my_answers_search = search
        self.my_answers_details = details
        self.my_answers_map = {}

        search.bind("<KeyRelease>", lambda _e: self._refresh_my_answers_view(), add="+")
        search.bind("<Return>", lambda _e: self._refresh_my_answers_view(), add="+")
        search.bind("<Escape>", lambda _e: self._close_my_answers_window(), add="+")
        tree.bind("<<TreeviewSelect>>", self._show_selected_my_answer, add="+")
        win.protocol("WM_DELETE_WINDOW", self._close_my_answers_window)

        self._set_my_answer_details("Загрузка истории ответов...")
        self._load_my_answers()
        try:
            self.btn_my_answers.config(text="Скрыть мои ответы")
        except Exception:
            pass

    def _close_my_answers_window(self):
        try:
            if self.my_answers_win and self.my_answers_win.winfo_exists():
                self.my_answers_win.destroy()
        except Exception:
            pass
        self.my_answers_win = None
        self.my_answers_tree = None
        self.my_answers_search = None
        self.my_answers_details = None
        self.my_answers_map = {}
        self.my_answers_focus_order_id = None
        try:
            self.btn_my_answers.config(text="Мои ответы")
        except Exception:
            pass

    def _update_profile_labels(self):
        # Обновляет надписи автозаполнения (если виджеты уже созданы)
        try:
            if hasattr(self, "contact_lbl"):
                self.contact_lbl.config(text=self.profile_phone or "—")
            if hasattr(self, "company_lbl"):
                self.company_lbl.config(text=self.profile_company or self.profile_username or "—")
        except Exception:
            pass

    def _clear_offer_fields(self):
        # очищаем только то, что пользователь реально вводит
        try:
            self.price_e.delete(0, tk.END)
            self.price_e.insert(0, PH_PRICE)
        except Exception:
            pass
        try:
            self.comment_e.delete(0, tk.END)
            self.comment_e.insert(0, PH_COMMENT)
        except Exception:
            pass

    def _selected_order(self) -> Optional[IncomingOrder]:
        sel = self.tree.selection()
        if not sel:
            return None
        item = sel[0]
        return self.orders_by_item.get(item)

    def _on_select_order(self, _event=None):
        order = self._selected_order()
        if not order:
            return

        self.status_lbl.config(text=f"Выбрана заявка #{order.id}")
        if self.my_answers_win and self.my_answers_win.winfo_exists() and self.sent_offers.get(order.id):
            self.my_answers_focus_order_id = int(order.id)
            self._refresh_my_answers_view()

    def _refresh_incoming_orders(self, initial=False):
        def work():
            return self.http.get(f"{API_URL}/market/orders?status=open", timeout=HTTP_TIMEOUT)

        def on_ok(resp: requests.Response):
            if resp.status_code == 401:
                error(self.root, "Сессия", "Токен недействителен. Нужно войти заново.")
                self._stop_polling()
                return

            if resp.status_code != 200:
                j = safe_json(resp)
                warn(self.root, "Сервер", f"Не удалось получить заявки: {resp.status_code}\n{j or resp.text}")
                return

            orders = resp.json()
            if isinstance(orders, dict) and isinstance(orders.get('items'), list):
                orders = orders.get('items')
            if not isinstance(orders, list):
                return

            # сохраняем выделение и скролл перед авто-обновлением
            selected_order_id = None
            try:
                sel = self.tree.selection()
                if sel:
                    old = self.orders_by_item.get(sel[0])
                    if old:
                        selected_order_id = int(old.id)
            except Exception:
                selected_order_id = None
            try:
                y0 = self.tree.yview()[0]
            except Exception:
                y0 = 0.0

            self.tree.delete(*self.tree.get_children())
            self.orders_by_item.clear()

            for o in orders:
                try:
                    oid = int(o.get("id"))
                except Exception:
                    continue

                order = IncomingOrder(
                    id=oid,
                    direction=str(repair_mojibake_text(o.get("direction") or "")),
                    cargo=str(repair_mojibake_text(o.get("cargo") or "")),
                    tonnage=float(o.get("tonnage") or 0),
                    truck=str(repair_mojibake_text(o.get("truck") or "")),
                    date=str(repair_mojibake_text(o.get("date") or "")),
                    budget_price=float(o.get("price") or 0),
                    info=str(repair_mojibake_text(o.get("info") or "")),
                    from_company=str(repair_mojibake_text(o.get("from_company") or "")),
                )

                cargo_disp = f"{order.cargo} {order.tonnage}т".strip()
                my_offer = self.sent_offers.get(order.id, {}).get("price", "")

                item = self.tree.insert(
                    "",
                    "end",
                    values=(
                        UNCHECKED,
                        order.id,
                        order.direction,
                        cargo_disp,
                        order.truck,
                        order.date,
                        f"{order.budget_price}$" if order.budget_price else "",
                        order.info,
                        f"{my_offer}$" if my_offer else "",
                    ),
                )
                self.orders_by_item[item] = order

            if initial:
                self.status_lbl.config(text=f"Загружено заявок: {len(orders)}")

        self._run_http_async(work, on_ok=on_ok)

    def _send_offer(self):
        order = self._selected_order()
        if not order:
            warn(self.root, "Выбор", "Выберите заявку в списке")
            return

        price_raw = self.price_e.get().strip()
        if price_raw in (PH_PRICE, ""):
            error(self.root, "Ошибка", "Укажите цену")
            return

        try:
            price = int(float(price_raw))
        except Exception:
            error(self.root, "Ошибка", "Цена должна быть числом")
            return

        comment = self.comment_e.get().strip()
        if comment == PH_COMMENT:
            comment = ""

        contact = (self.contact_var.get() or "").strip()
        company = (self.company_var.get() or "").strip()

        if not contact or not company:
            error(self.root, "Ошибка", "Заполните телефон и компанию (или разморозьте и заполните).")
            return

        # сохраняем всегда (чтобы автозаполнялось в будущем)
        if self.profile_username:
            _save_profile(self.profile_username, contact, company, frozen=self.freeze_var.get())

        payload = {"order_id": order.id, "price": price, "comment": comment, "contact": contact, "company": company}

        def work():
            return self.http.post(f"{API_URL}/market/offer", json=payload, timeout=HTTP_TIMEOUT)

        def on_ok(resp: requests.Response):
            if resp.status_code in (200, 201):
                offer_created_at = int(time.time())
                self.sent_offers[order.id] = {
                    "price": price,
                    "comment": comment,
                    "contact": contact,
                    "company": company,
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(offer_created_at)),
                    "offer_created_at": offer_created_at,
                    "transport_username": self.profile_username,
                    "order": self._snapshot_order(order),
                }
                self._save_local_offers()
                if self.my_answers_win is not None and self.my_answers_win.winfo_exists():
                    self.my_answers_focus_order_id = int(order.id)
                    self._load_my_answers()

                info(self.root, "Готово", f"Оффер отправлен по заявке #{order.id}")
                self.status_lbl.config(text=f"Оффер отправлен: #{order.id} — {price}$")
                self._refresh_incoming_orders()
            else:
                j = safe_json(resp)
                error(self.root, "Ошибка", f"{resp.status_code}\n{j or resp.text}")

        self._run_http_async(work, on_ok=on_ok)

    def _update_auto_btn(self):
        btn = getattr(self, "auto_btn", None)
        if not btn:
            return
        if self.auto_refresh_enabled:
            btn.config(text="⏸ Авто-обновление: ВКЛ", bg=BTN_SUCCESS, fg="white")
        else:
            btn.config(text="▶ Авто-обновление: ВЫКЛ", bg=BTN_DANGER, fg="white")

    def _toggle_auto_refresh(self):
        self.auto_refresh_enabled = not self.auto_refresh_enabled
        self._update_auto_btn()
        if self.auto_refresh_enabled:
            self.status_lbl.config(text="Авто-обновление включено")
        else:
            self.status_lbl.config(text="Авто-обновление выключено")

    def _start_polling(self):
        if self.polling_active:
            return
        self.polling_active = True
        self._update_auto_btn()
        self.status_lbl.config(text="Авто-обновление включено")
        self.root.after(POLL_INTERVAL_MS, self._poll_tick)

    def _stop_polling(self):
        self.polling_active = False
        self.auto_refresh_enabled = True
        self.status_lbl.config(text="Авто-обновление остановлено")

    def _poll_tick(self):
        if not self.polling_active:
            return
        if self.auto_refresh_enabled:
            self._refresh_incoming_orders()
        self.root.after(POLL_INTERVAL_MS, self._poll_tick)

    def on_order_click(self, event):
        """
        Клик по таблице заявок:
        - по первой колонке (галочка) переключает ☑/☐
        - иначе оставляет обычное поведение выбора строки
        """
        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if item and col == "#1":
            values = list(self.tree.item(item, "values") or [])
            if values:
                values[0] = CHECKED if values[0] == UNCHECKED else UNCHECKED
                self.tree.item(item, values=values)
            return "break"
        self.root.after(10, self._on_select_order)


def login_to_server(root: tk.Tk) -> Tuple[Optional[str], str]:
    win = tk.Toplevel(root)
    win.title("Transport — Вход / Регистрация")
    win.geometry("440x390")
    win.resizable(False, False)
    win.configure(bg=BG_MAIN)
    win.grab_set()
    disable_tk_bell(win)
    apply_global_font(win)
    _set_window_icon(win)

    panel = tk.Frame(win, bg=BG_PANEL, padx=20, pady=20, highlightthickness=1, highlightbackground=BORDER)
    panel.place(relx=0.5, rely=0.5, anchor="c", width=380, height=330)

    title = tk.Label(panel, text="Transport", bg=BG_PANEL, fg=ACCENT, font=(APP_FONT_FAMILY, 18, "bold"))
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
                json={"username": u, "password": p, "device_id": get_device_id(), "app": "transport"},
                timeout=HTTP_TIMEOUT,
            )
            if r.status_code != 200:
                j = safe_json(r)
                if isinstance(j, dict) and j.get("error") in ("license_inactive", "license_expired", "license_not_found"):
                    code_msg = {
                        "license_inactive": "Ключ продукта отключён администратором.",
                        "license_expired": "Срок действия ключа продукта истёк.",
                        "license_not_found": "Ключ продукта не найден.",
                    }.get(j.get("error"), "Доступ по ключу продукта недоступен.")
                    error(win, "Доступ отключён", f"{code_msg}")
                else:
                    error(win, "Ошибка", "Неверно указан логин или пароль")
                return

            data = r.json()
            token = data.get("token")
            role = (data.get("role") or "").lower()

            if role not in ("transport", "admin"):
                error(
                    win,
                    "Ошибка",
                    "Проверьте логин и пароль",
                )
                return

            if not token:
                error(win, "Ошибка", "Сервер не вернул token")
                return

            if remember.get():
                try:
                    with open(TRANSPORT_TOKEN_FILE, "w", encoding="utf-8") as f:
                        f.write(token)
                except Exception:
                    pass

            result["token"] = token
            result["username"] = u
            win.destroy()

        except Exception as e:
            error(win, "Ошибка", f"Не удалось подключиться к серверу:\n{e}")

    def open_register_window(parent_win):
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
        code_e = labeled(panel2, "Ключ продукта")
        code2_e = labeled(panel2, "Подтверждение ключа")

        def do_register_real():
            u = u_e.get().strip()
            p = p_e.get().strip()
            email = email_e.get().strip()
            phone = phone_e.get().strip()
            company_name = company_e.get().strip()
            code = code_e.get().strip()
            code2 = code2_e.get().strip()

            if not u or not p or not email or not phone or not company_name or not code or not code2:
                error(reg, "Ошибка", "Заполните все поля")
                return

            if not phone.isdigit():
                error(reg, "Ошибка", "Номер телефона должен содержать только цифры")
                return

            if code != code2:
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
                        "license_key": code,
                        "license_key_confirm": code2,
                        "device_id": get_device_id(),
                        "role": "transport",
                    },
                    timeout=HTTP_TIMEOUT,
                )

                if r.status_code != 201:
                    j = safe_json(r)
                    error(reg, "Ошибка", f"Регистрация не прошла: {r.status_code}\n{j or r.text}")
                    return

                _save_profile(u, phone, company_name)
                info(reg, "Готово", "Аккаунт создан. Теперь войдите.")
                reg.destroy()

                user_e.delete(0, tk.END)
                user_e.insert(0, u)
                pass_e.delete(0, tk.END)
                pass_e.focus_set()

            except Exception as e:
                error(reg, "Ошибка", f"Не удалось подключиться к серверу:\n{e}")

        modern_button(panel2, "Зарегистрироваться", do_register_real, variant="accent").pack(
            fill="x", padx=18, pady=(8, 10)
        )

        reg.bind("<Return>", lambda _e: do_register_real())
        reg.bind("<Escape>", lambda _e: reg.destroy())
        u_e.focus_set()

    modern_button(panel, "Войти", do_login, variant="accent").pack(fill="x", padx=18, pady=(0, 8))
    modern_button(panel, "Регистрация", lambda: open_register_window(win), variant="secondary").pack(fill="x", padx=18, pady=(0, 12))

    win.bind("<Return>", lambda _e: do_login())
    user_e.focus_set()

    root.wait_window(win)
    return result["token"], result.get("username", "")


def try_restore_token() -> Optional[str]:
    p = TRANSPORT_TOKEN_FILE
    if not os.path.exists(p):
        return None

    try:
        t = open(p, "r", encoding="utf-8").read().strip()
        if not t:
            return None

        chk = requests.get(
            f"{API_URL}/market/orders?status=open",
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
    root.withdraw()

    token = try_restore_token()
    username = ""

    # 1) Если токен восстановился — узнаём username через /me
    if token:
        try:
            r = requests.get(f"{API_URL}/me", headers={"Authorization": f"Bearer {token}"}, timeout=HTTP_TIMEOUT)
            if r.status_code == 200:
                meta = r.json() if isinstance(r.json(), dict) else {}
                username = (meta.get("username") or "").strip()
                phone = (meta.get('phone') or '').strip()
                company = (meta.get('company_name') or '').strip()
                if username and phone:
                    _save_profile(username, phone, company)
                phone = (meta.get('phone') or '').strip()
                company = (meta.get('company_name') or '').strip()
                if username and phone:
                    _save_profile(username, phone, company)
        except Exception:
            pass

    # 2) Если токена нет (или username не удалось получить) — показываем окно логина
    if not token:
        token, username = login_to_server(root)

    if not token:
        root.destroy()
        raise SystemExit(0)

    # На всякий случай: если username всё ещё пустой — пробуем /me ещё раз
    if not username:
        try:
            r = requests.get(f"{API_URL}/me", headers={"Authorization": f"Bearer {token}"}, timeout=HTTP_TIMEOUT)
            if r.status_code == 200:
                meta = r.json() if isinstance(r.json(), dict) else {}
                username = (meta.get("username") or "").strip()
        except Exception:
            pass

    root.deiconify()
    app = TransportApp(root, token, username=username)
    root.mainloop()











