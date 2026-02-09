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

# ================== CONFIG ==================
LOGIN_ICON_PATH = r"Theresa.ico"
LOGIN_BG_PATH = r"login_background.jpg"

API_URL = os.getenv("API_URL", "http://34.179.169.197")

POLL_INTERVAL_MS = 4000
HTTP_TIMEOUT = 8

# ================== UI THEME ==================
BG_MAIN = "#1e1e1e"
BG_PANEL = "#252526"
FG_TEXT = "#ffffff"
ACCENT = "#2a82da"
ENTRY_BG = "#333333"
ENTRY_FG = "#ffffff"
PLACEHOLDER_FG = "grey"

CHECKED = "☑"
UNCHECKED = "☐"

APP_FONT_FAMILY = os.getenv("APP_FONT_FAMILY", "Segoe UI")
APP_FONT_SIZE = int(os.getenv("APP_FONT_SIZE", "10"))
APP_FONT = (APP_FONT_FAMILY, APP_FONT_SIZE)
APP_FONT_BOLD = (APP_FONT_FAMILY, APP_FONT_SIZE, "bold")

PH_PRICE = "Например: 1200"
PH_COMMENT = "Например: можем сегодня, оплата нал/перечисление"
PH_CONTACT = "+99890... или @username"
PH_COMPANY = "Например: TruckLine / Aziz"


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
    win = tk.Toplevel(parent)
    win.title(title)
    _set_window_icon(win)
    win.configure(bg=BG_MAIN)

    win.transient(parent.winfo_toplevel())
    win.grab_set()
    disable_tk_bell(win)

    body = tk.Frame(win, bg=BG_MAIN)
    body.pack(fill="both", expand=True, padx=16, pady=16)

    win.update_idletasks()
    screen_w = win.winfo_screenwidth()
    screen_h = win.winfo_screenheight()

    max_text_w = min(720, int(screen_w * 0.70))
    min_win_w = 360
    min_win_h = 160

    msg = tk.Label(
        body,
        text=text,
        bg=BG_MAIN,
        fg=FG_TEXT,
        justify="left",
        anchor="nw",
        wraplength=max_text_w,
        font=APP_FONT,
    )
    msg.pack(fill="both", expand=True, pady=(0, 12))

    btn_bg = ACCENT
    if kind == "warning":
        btn_bg = "#F39C12"
    elif kind == "error":
        btn_bg = "#F44336"

    def close():
        try:
            win.grab_release()
        except Exception:
            pass
        win.destroy()

    tk.Button(
        body,
        text="OK",
        command=close,
        bg=btn_bg,
        fg="white",
        bd=0,
        padx=18,
        pady=8,
        font=APP_FONT_BOLD,
        activebackground=btn_bg,
        activeforeground="white",
    ).pack(anchor="e")

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

        root.title("Transport Manager — Входящие заявки")
        root.geometry("1400x780")
        root.configure(bg=BG_MAIN)

        self._init_styles()

        self._build_left_panel()
        self._build_center_panel()
        self._build_right_panel()

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
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(
            "Dark.Treeview",
            background=BG_PANEL,
            fieldbackground=BG_PANEL,
            foreground=FG_TEXT,
            rowheight=24,
            font=APP_FONT,
        )
        style.configure(
            "Dark.Treeview.Heading",
            background="#2d2d2d",
            foreground=FG_TEXT,
            font=APP_FONT_BOLD,
        )
        style.map(
            "Dark.Treeview",
            background=[("selected", "#3a3d41")],
            foreground=[("selected", FG_TEXT)],
        )

        style.configure(
            "Thin.Vertical.TScrollbar",
            gripcount=0,
            borderwidth=0,
            troughcolor=BG_PANEL,
            background="#444444",
        )
        style.configure(
            "Thin.Horizontal.TScrollbar",
            gripcount=0,
            borderwidth=0,
            troughcolor=BG_PANEL,
            background="#444444",
        )

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
                data = json.load(f)
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

    def _build_left_panel(self):
        left = tk.Frame(self.root, bg=BG_PANEL, padx=12, pady=12)
        left.pack(side="left", fill="y")

        tk.Label(left, text="Оффер по выбранной заявке", bg=BG_PANEL, fg=FG_TEXT, font=APP_FONT_BOLD).pack(
            anchor="w", pady=(0, 10)
        )

        tk.Label(left, text="Цена (обязательно)", bg=BG_PANEL, fg=FG_TEXT).pack(anchor="w")
        self.price_e = tk.Entry(left, bg=ENTRY_BG, fg=ENTRY_FG, insertbackground="white", width=35)
        self.price_e.pack(pady=4)
        self._add_placeholder(self.price_e, PH_PRICE)

        tk.Label(left, text="Комментарий (необязательно)", bg=BG_PANEL, fg=FG_TEXT).pack(anchor="w")
        self.comment_e = tk.Entry(left, bg=ENTRY_BG, fg=ENTRY_FG, insertbackground="white", width=35)
        self.comment_e.pack(pady=4)
        self._add_placeholder(self.comment_e, PH_COMMENT)

        tk.Label(left, text="Телефон (для контакта)", bg=BG_PANEL, fg=FG_TEXT).pack(anchor="w", pady=(10, 0))
        self.contact_var = tk.StringVar(value=self.profile_phone or "")
        self.contact_e2 = tk.Entry(left, textvariable=self.contact_var, bg=ENTRY_BG, fg=ENTRY_FG,
                                   insertbackground="white", width=35)
        self.contact_e2.pack(pady=4)

        tk.Label(left, text="Компания", bg=BG_PANEL, fg=FG_TEXT).pack(anchor="w")
        self.company_var = tk.StringVar(value=self.profile_company or "")
        self.company_e2 = tk.Entry(left, textvariable=self.company_var, bg=ENTRY_BG, fg=ENTRY_FG,
                                   insertbackground="white", width=35)
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

        tk.Button(left, text="📨 Отправить оффер", bg=ACCENT, fg="white", command=self._send_offer).pack(
            pady=10, fill="x"
        )

        tk.Button(left, text="🧹 Очистить поля", bg="#607D8B", fg="white", command=self._clear_offer_fields).pack(
            pady=5, fill="x"
        )

        tk.Label(left, text="Статус:", bg=BG_PANEL, fg=FG_TEXT).pack(anchor="w", pady=(20, 0))
        self.status_lbl = tk.Label(left, text="—", bg=BG_PANEL, fg=FG_TEXT)
        self.status_lbl.pack(anchor="w")

        self.auto_btn = tk.Button(
            left,
            text="⏸ Авто-обновление: ВКЛ",
            bg="#4CAF50",
            fg="white",
            command=self._toggle_auto_refresh,
        )
        self.auto_btn.pack(fill="x", pady=(10, 0))

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

    def _build_right_panel(self):
        right = tk.Frame(self.root, bg=BG_PANEL, padx=12, pady=12)
        right.pack(side="right", fill="y")

        tk.Label(
            right,
            text="Детали заявки",
            bg=BG_PANEL,
            fg=FG_TEXT,
            font=APP_FONT_BOLD,
        ).pack(anchor="w", pady=(0, 8))

        # --- Text + AutoScrollbars (вертикальный + горизонтальный, автоскрытие) ---
        wrap = tk.Frame(right, bg=BG_PANEL)
        wrap.pack(fill="both", expand=True)

        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)

        ybar = AutoScrollbar(wrap, orient="vertical", style="Thin.Vertical.TScrollbar")
        xbar = AutoScrollbar(wrap, orient="horizontal", style="Thin.Horizontal.TScrollbar")

        self.details = tk.Text(
            wrap,
            width=42,
            height=26,
            bg=ENTRY_BG,
            fg=FG_TEXT,
            insertbackground="white",
            wrap="none",  # важно для горизонтального скролла
            yscrollcommand=ybar.set,
            xscrollcommand=xbar.set,
        )
        self.details.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")

        ybar.config(command=self.details.yview)
        xbar.config(command=self.details.xview)

        tk.Button(
            right,
            text="📋 Копировать детали",
            bg=ACCENT,
            fg="white",
            command=self._copy_details,
        ).pack(pady=10, fill="x")

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

        text = (
            f"ID: {order.id}\n"
            f"Направление: {order.direction}\n"
            f"Груз: {order.cargo}\n"
            f"Тоннаж: {order.tonnage}\n"
            f"Транспорт: {order.truck}\n"
            f"Дата: {order.date}\n"
            f"Бюджет: {order.budget_price}\n"
            f"Требования: {order.info}\n"
        )
        if order.from_company:
            text += f"\nОт (логист): {order.from_company}\n"

        existing = self.sent_offers.get(order.id)
        if existing:
            text += "\n--- МОЙ ОТВЕТ ---\n"
            text += f"Цена: {existing.get('price')}\n"
            text += f"Контакт: {existing.get('contact')}\n"
            text += f"Комментарий: {existing.get('comment')}\n"
            text += f"Кто: {existing.get('company')}\n"
            text += f"Время: {existing.get('ts')}\n"

        self.details.delete("1.0", tk.END)
        self.details.insert(tk.END, text)
        self.status_lbl.config(text=f"Выбрана заявка #{order.id}")

    def _copy_details(self):
        data = self.details.get("1.0", tk.END).strip()
        if not data:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(data)
        info(self.root, "Готово", "Скопировано в буфер обмена")

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
                    direction=str(o.get("direction") or ""),
                    cargo=str(o.get("cargo") or ""),
                    tonnage=float(o.get("tonnage") or 0),
                    truck=str(o.get("truck") or ""),
                    date=str(o.get("date") or ""),
                    budget_price=float(o.get("price") or 0),
                    info=str(o.get("info") or ""),
                    from_company=str(o.get("from_company") or ""),
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
                self.sent_offers[order.id] = {
                    "price": price,
                    "comment": comment,
                    "contact": contact,
                    "company": company,
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                self._save_local_offers()

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
            btn.config(text="⏸ Авто-обновление: ВКЛ", bg="#4CAF50", fg="white")
        else:
            btn.config(text="▶ Авто-обновление: ВЫКЛ", bg="#F44336", fg="white")

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

    title = tk.Label(panel, text="Transport", bg=BG_PANEL, fg=FG_TEXT, font=(APP_FONT_FAMILY, 16, "bold"))
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
                    with open("transport_auth_token.txt", "w", encoding="utf-8") as f:
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
        reg.geometry("420x610")
        reg.resizable(False, False)
        reg.configure(bg=BG_MAIN)
        reg.grab_set()
        disable_tk_bell(reg)
        _set_window_icon(reg)

        panel2 = tk.Frame(reg, bg=BG_PANEL)
        panel2.place(relx=0.5, rely=0.5, anchor="c", width=420, height=610)

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
        email_e = labeled(panel2, "Почта (email)")
        phone_e = labeled(panel2, "Номер телефона")
        code_e = labeled(panel2, "Ключ продукта")

        def do_register_real():
            u = u_e.get().strip()
            p = p_e.get().strip()
            email = email_e.get().strip()
            phone = phone_e.get().strip()
            code = code_e.get().strip()

            if not u or not p or not email or not phone or not code:
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
                        "license_key": code,
                        "device_id": get_device_id(),
                        "role": "transport",
                    },
                    timeout=HTTP_TIMEOUT,
                )

                if r.status_code != 201:
                    j = safe_json(r)
                    error(reg, "Ошибка", f"Регистрация не прошла: {r.status_code}\n{j or r.text}")
                    return

                    _save_profile(u, phone, "")
                info(reg, "Готово", "Аккаунт создан. Теперь войдите.")
                reg.destroy()

                user_e.delete(0, tk.END)
                user_e.insert(0, u)
                pass_e.delete(0, tk.END)
                pass_e.focus_set()

            except Exception as e:
                error(reg, "Ошибка", f"Не удалось подключиться к серверу:\n{e}")

        tk.Button(panel2, text="Зарегистрироваться", bg=ACCENT, fg="white", command=do_register_real).pack(
            fill="x", padx=18, pady=(8, 10)
        )

        reg.bind("<Return>", lambda _e: do_register_real())
        u_e.focus_set()

    tk.Button(panel, text="Войти", bg=ACCENT, fg="white", command=do_login).pack(fill="x", padx=18, pady=(0, 8))
    tk.Button(panel, text="Регистрация", bg="#607D8B", fg="white", command=lambda: open_register_window(win)).pack(
        fill="x", padx=18, pady=(0, 12)
    )

    win.bind("<Return>", lambda _e: do_login())
    user_e.focus_set()

    root.wait_window(win)
    return result["token"], result.get("username", "")


def try_restore_token() -> Optional[str]:
    p = "transport_auth_token.txt"
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
