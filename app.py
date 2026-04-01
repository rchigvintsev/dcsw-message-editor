"""
DCS World Mission Message Editor — main application window.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from collections import OrderedDict
from typing import Dict, Optional

import ttkbootstrap as ttk
from ttkbootstrap.constants import *

import parser as dict_parser
import miz as miz_helper

# ── Constants ────────────────────────────────────────────────────────────────

APP_TITLE = "DCS World — Mission Message Editor"
DARK_THEME = "darkly"
LIGHT_THEME = "flatly"

COL_KEY = "Ключ"
COL_VALUE = "Значение"
COL_WIDTHS = {COL_KEY: 260, COL_VALUE: 700}

FILTER_PLACEHOLDER = "Поиск по ключу или значению…"

# Lua line-continuation sequence stored inside values: backslash + newline
_LUA_NEWLINE = "\\\n"  # two chars: \ and \n


def _to_display(value: str) -> str:
    """Collapse Lua line-continuation sequences to spaces for single-line table display.

    The file stores multi-line values as:  text\\\nmore text
    Paragraph breaks are:  text\\\n\\\nmore text  (a line containing only \\)
    Both are collapsed to a single space so the table cell stays on one line.
    """
    # Replace the continuation sequence (backslash + newline) with a space,
    # then strip any lone backslashes left on what were paragraph-break lines.
    return value.replace(_LUA_NEWLINE, " ").replace("\\", "")


def _to_editor(value: str) -> str:
    """Convert internal value to human-readable multiline text for the editor.

    ``\\\\\\n`` (backslash + newline) → plain ``\\n`` so the user sees real line breaks.
    A paragraph-break line (containing only ``\\\\``) becomes an empty line.
    """
    return value.replace(_LUA_NEWLINE, "\n")


def _from_editor(text: str) -> str:
    """Convert editor text back to internal Lua continuation format.

    The editor shows plain newlines; internally values use ``\\\\\\n``
    (backslash + newline) as the line-continuation sequence.
    An empty editor line represents a Lua paragraph-break line that contains
    only ``\\\\`` — but since we join with ``\\\\\\n``, the empty string between
    two ``\\\\\\n`` markers already produces the correct ``\\\\\\n\\\\\\n`` sequence.
    """
    return text.replace("\n", _LUA_NEWLINE)

# ── Editor dialog ─────────────────────────────────────────────────────────────

class ValueEditorDialog(tk.Toplevel):
    """Modal dialog for editing a single dictionary value."""

    def __init__(self, parent: tk.Widget, key: str, value: str) -> None:
        super().__init__(parent)
        self.title(f"Редактирование: {key}")
        self.resizable(True, True)
        self.grab_set()

        self.result: Optional[str] = None

        frame = ttk.Frame(self, padding=12)
        frame.pack(fill=BOTH, expand=YES)

        ttk.Label(frame, text=f"Ключ: {key}", font=("", 10, "bold")).pack(anchor=W, pady=(0, 6))

        self._text = tk.Text(frame, wrap=WORD, width=80, height=14, font=("Consolas", 10))
        self._text.insert("1.0", _to_editor(value))
        self._text.pack(fill=BOTH, expand=YES)

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=X, pady=(10, 0))
        ttk.Button(btn_row, text="Сохранить", bootstyle=SUCCESS, command=self._save).pack(side=RIGHT, padx=(6, 0))
        ttk.Button(btn_row, text="Отмена", bootstyle=SECONDARY, command=self.destroy).pack(side=RIGHT)

        self.update_idletasks()
        self._center(parent)

    def _center(self, parent: tk.Widget) -> None:
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

    def _save(self) -> None:
        # Convert plain newlines back to Lua line-continuation sequences
        self.result = _from_editor(self._text.get("1.0", "end-1c"))
        self.destroy()


# ── Main application ──────────────────────────────────────────────────────────

class App(ttk.Window):
    def __init__(self) -> None:
        super().__init__(themename=DARK_THEME)
        self.title(APP_TITLE)
        self.geometry("1200x700")
        self.minsize(800, 500)

        # ── Source: either a plain dictionary file or a .miz archive ──
        self._miz_path: Optional[Path] = None          # set when a .miz is open
        self._dict_path: Optional[Path] = None         # set when a plain file is open
        # All locales loaded from the current source: {locale: entries}
        self._all_entries: Dict[str, OrderedDict[str, str]] = {}
        # Currently displayed locale
        self._current_locale: str = ""
        # Shortcut to self._all_entries[self._current_locale]
        self._entries: OrderedDict[str, str] = OrderedDict()

        self._is_dark: bool = True

        self._build_ui()
        self._update_title()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ── Top toolbar ──
        toolbar = ttk.Frame(self, padding=(8, 6))
        toolbar.pack(fill=X, side=TOP)

        ttk.Button(toolbar, text="📂 Открыть", bootstyle=PRIMARY, command=self._open_file).pack(side=LEFT, padx=(0, 4))
        self._btn_apply = ttk.Button(toolbar, text="✔ Применить", bootstyle=SUCCESS, command=self._apply, state=DISABLED)
        self._btn_apply.pack(side=LEFT, padx=4)
        self._btn_revert = ttk.Button(toolbar, text="✖ Отменить всё", bootstyle=DANGER, command=self._revert, state=DISABLED)
        self._btn_revert.pack(side=LEFT, padx=4)

        ttk.Separator(toolbar, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=8)
        self._btn_delete = ttk.Button(toolbar, text="🗑 Удалить строку", bootstyle=(DANGER, OUTLINE), command=self._delete_selected, state=DISABLED)
        self._btn_delete.pack(side=LEFT)

        # ── Locale selector (hidden until a source with multiple locales is open) ──
        self._locale_frame = ttk.Frame(toolbar)
        self._locale_frame.pack(side=LEFT, padx=(16, 0))
        ttk.Label(self._locale_frame, text="Локаль:").pack(side=LEFT, padx=(0, 4))
        self._locale_var = tk.StringVar()
        self._locale_cb = ttk.Combobox(
            self._locale_frame,
            textvariable=self._locale_var,
            state="readonly",
            width=16,
        )
        self._locale_cb.pack(side=LEFT)
        self._locale_cb.bind("<<ComboboxSelected>>", self._on_locale_changed)
        self._btn_delete_locale = ttk.Button(
            self._locale_frame,
            text="🗑",
            bootstyle=(DANGER, OUTLINE),
            width=3,
            command=self._delete_locale,
        )
        self._btn_delete_locale.pack(side=LEFT, padx=(4, 0))
        ttk.Label(self._locale_frame, text="— удалить локаль").pack(side=LEFT, padx=(2, 0))
        self._locale_frame.pack_forget()  # hidden by default

        # Theme toggle (right side)
        self._theme_btn = ttk.Button(toolbar, text="☀ Светлая тема", bootstyle=SECONDARY, command=self._toggle_theme)
        self._theme_btn.pack(side=RIGHT, padx=(4, 0))

        # ── Filter bar ──
        filter_frame = ttk.Frame(self, padding=(8, 0, 8, 4))
        filter_frame.pack(fill=X, side=TOP)

        ttk.Label(filter_frame, text="🔍").pack(side=LEFT, padx=(0, 4))
        self._filter_entry = ttk.Entry(filter_frame, width=60)
        self._filter_entry.pack(side=LEFT, fill=X, expand=YES)
        self._filter_entry.bind("<FocusIn>", self._on_filter_focus_in)
        self._filter_entry.bind("<FocusOut>", self._on_filter_focus_out)
        self._filter_entry.bind("<KeyRelease>", lambda _e: self._apply_filter())
        self._set_filter_placeholder()

        ttk.Button(filter_frame, text="✕", bootstyle=(SECONDARY, OUTLINE), width=3,
                   command=self._clear_filter).pack(side=LEFT, padx=(4, 0))

        # ── Status bar ──
        self._status_var = tk.StringVar(value="Откройте файл dictionary или архив *.miz для начала работы.")
        status_bar = ttk.Label(self, textvariable=self._status_var, anchor=W, padding=(8, 3))
        status_bar.pack(fill=X, side=BOTTOM)
        ttk.Separator(self, orient=HORIZONTAL).pack(fill=X, side=BOTTOM)

        # ── Table (Treeview) ──
        table_frame = ttk.Frame(self)
        table_frame.pack(fill=BOTH, expand=YES, padx=8, pady=(0, 4))

        columns = (COL_KEY, COL_VALUE)
        self._tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")

        self._tree.heading(COL_KEY,   text=COL_KEY,   command=lambda: self._sort_by(COL_KEY))
        self._tree.heading(COL_VALUE, text=COL_VALUE, command=lambda: self._sort_by(COL_VALUE))

        self._tree.column(COL_KEY,   width=COL_WIDTHS[COL_KEY],   stretch=False, minwidth=80)
        self._tree.column(COL_VALUE, width=COL_WIDTHS[COL_VALUE], stretch=True,  minwidth=120)

        vsb = ttk.Scrollbar(table_frame, orient=VERTICAL, command=self._tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient=HORIZONTAL, command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        self._tree.bind("<Double-1>", self._on_double_click)
        self._tree.bind("<Return>", self._on_double_click)

        # Track sort state
        self._sort_col: Optional[str] = None
        self._sort_reverse: bool = False

    # ── Filter helpers ────────────────────────────────────────────────────────

    def _set_filter_placeholder(self) -> None:
        self._filter_entry.delete(0, END)
        self._filter_entry.insert(0, FILTER_PLACEHOLDER)
        self._filter_entry.configure(foreground="gray")
        self._placeholder_active = True

    def _on_filter_focus_in(self, _event: tk.Event) -> None:
        if getattr(self, "_placeholder_active", False):
            self._filter_entry.delete(0, END)
            self._filter_entry.configure(foreground="")
            self._placeholder_active = False

    def _on_filter_focus_out(self, _event: tk.Event) -> None:
        if not self._filter_entry.get():
            self._set_filter_placeholder()

    def _clear_filter(self) -> None:
        self._set_filter_placeholder()
        self._populate_tree("")

    def _apply_filter(self) -> None:
        # Ignore key events while placeholder is shown
        if getattr(self, "_placeholder_active", False):
            return
        query = self._filter_entry.get().strip().lower()
        self._populate_tree(query)

    # ── File operations ───────────────────────────────────────────────────────

    def _open_file(self) -> None:
        path_str = filedialog.askopenfilename(
            title="Открыть файл dictionary или архив *.miz",
            filetypes=[
                ("DCS Mission / Dictionary", "*.miz dictionary"),
                ("DCS Mission (*.miz)", "*.miz"),
                ("DCS Dictionary", "dictionary"),
                ("Все файлы", "*.*"),
            ],
        )
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix.lower() == ".miz":
            self._load_miz(path)
        else:
            self._load_plain(path)

    # ── Loading: plain dictionary file ───────────────────────────────────────

    def _load_plain(self, path: Path) -> None:
        try:
            entries = dict_parser.parse(path)
        except Exception as exc:
            messagebox.showerror("Ошибка загрузки", str(exc))
            return

        locale = path.parent.name
        self._miz_path = None
        self._dict_path = path
        self._all_entries = {locale: entries}
        self._switch_locale(locale, show_selector=False)
        self._update_title(filename=path.name, locale=locale)
        self._set_file_buttons_state(NORMAL)
        self._status(f"Загружено {len(entries)} записей  |  Локаль: {locale}  |  {path}")

    # ── Loading: .miz archive ─────────────────────────────────────────────────

    def _load_miz(self, path: Path) -> None:
        try:
            all_entries = miz_helper.open_miz(path)
        except Exception as exc:
            messagebox.showerror("Ошибка загрузки", str(exc))
            return

        self._miz_path = path
        self._dict_path = None
        self._all_entries = all_entries

        locales = sorted(all_entries.keys())
        # Prefer DEFAULT locale if present, otherwise take the first one
        initial_locale = "DEFAULT" if "DEFAULT" in all_entries else locales[0]

        self._locale_cb.configure(values=locales)
        self._locale_var.set(initial_locale)
        self._locale_frame.pack(side=LEFT, padx=(16, 0))  # show selector

        self._switch_locale(initial_locale, show_selector=True)
        self._update_title(filename=path.name, locale=initial_locale)
        self._set_file_buttons_state(NORMAL)
        self._status(
            f"Архив: {path.name}  |  Локалей: {len(locales)}  |  "
            f"Текущая: {initial_locale}  |  Записей: {len(all_entries[initial_locale])}"
        )

    def _switch_locale(self, locale: str, show_selector: bool) -> None:
        """Load the given locale's entries into the table."""
        self._current_locale = locale
        self._entries = self._all_entries[locale]
        self._populate_tree()
        if not show_selector:
            self._locale_frame.pack_forget()

    def _delete_locale(self) -> None:
        """Delete the currently selected locale from the .miz archive immediately."""
        if not self._miz_path:
            return
        locale = self._current_locale
        remaining = [l for l in self._all_entries if l != locale]

        if not remaining:
            messagebox.showerror(
                "Удаление невозможно",
                f"Локаль «{locale}» является единственной в архиве.\n"
                "Нельзя удалить все локали.",
            )
            return

        if not messagebox.askyesno(
            "Удалить локаль",
            f"Удалить локаль «{locale}» из архива «{self._miz_path.name}»?\n\n"
            "Это действие будет немедленно записано в файл.",
        ):
            return

        try:
            miz_helper.delete_locale_from_miz(self._miz_path, locale)
        except Exception as exc:
            messagebox.showerror("Ошибка", str(exc))
            return

        # Update in-memory state
        del self._all_entries[locale]
        next_locale = "DEFAULT" if "DEFAULT" in self._all_entries else remaining[0]
        locales = sorted(self._all_entries.keys())
        self._locale_cb.configure(values=locales)
        self._locale_var.set(next_locale)
        self._current_locale = next_locale
        self._entries = self._all_entries[next_locale]
        self._populate_tree()
        self._update_title(filename=self._miz_path.name, locale=next_locale)
        self._status(
            f"Локаль «{locale}» удалена из архива  |  "
            f"Осталось локалей: {len(locales)}  |  Текущая: {next_locale}"
        )

    def _on_locale_changed(self, _event: tk.Event) -> None:
        new_locale = self._locale_var.get()
        if new_locale == self._current_locale:
            return
        self._current_locale = new_locale
        self._entries = self._all_entries[new_locale]
        self._populate_tree()
        source = self._miz_path or self._dict_path
        self._update_title(filename=source.name if source else "", locale=new_locale)
        self._status(
            f"Локаль: {new_locale}  |  Записей: {len(self._entries)}"
            + (f"  |  {self._miz_path}" if self._miz_path else "")
        )

    # ── Apply / Revert ────────────────────────────────────────────────────────

    def _apply(self) -> None:
        try:
            if self._miz_path:
                miz_helper.save_miz(self._miz_path, self._current_locale, self._entries)
                self._status(f"Сохранено в архив: {self._miz_path}  |  Локаль: {self._current_locale}")
            elif self._dict_path:
                dict_parser.save(self._dict_path, self._entries)
                self._status(f"Файл сохранён: {self._dict_path}")
            else:
                messagebox.showwarning("Нет файла", "Сначала откройте файл dictionary или архив *.miz.")
        except Exception as exc:
            messagebox.showerror("Ошибка сохранения", str(exc))

    def _revert(self) -> None:
        if not messagebox.askyesno(
            "Отменить изменения",
            "Перезагрузить данные из файла? Все несохранённые изменения будут потеряны.",
        ):
            return
        if self._miz_path:
            self._load_miz(self._miz_path)
        elif self._dict_path:
            self._load_plain(self._dict_path)

    # ── Table population ──────────────────────────────────────────────────────

    def _populate_tree(self, filter_query: str = "") -> None:
        self._tree.delete(*self._tree.get_children())
        for key, value in self._entries.items():
            if filter_query and filter_query not in key.lower() and filter_query not in value.lower():
                continue
            # Collapse Lua line-continuations to spaces for single-line display
            display_value = _to_display(value)
            self._tree.insert("", END, iid=key, values=(key, display_value))
        self._update_row_count()

    def _update_row_count(self) -> None:
        visible = len(self._tree.get_children())
        total = len(self._entries)
        if visible < total:
            self._status(f"Показано {visible} из {total} записей")
        elif total:
            source = self._miz_path or self._dict_path
            self._status(f"Всего записей: {total}  |  {source}")

    # ── Editing ───────────────────────────────────────────────────────────────

    def _on_double_click(self, event: tk.Event) -> None:
        item = self._tree.focus()
        if not item:
            return
        key = item  # iid == key
        value = self._entries.get(key, "")
        dlg = ValueEditorDialog(self, key, value)
        self.wait_window(dlg)
        if dlg.result is not None:
            self._entries[key] = dlg.result
            self._tree.item(item, values=(key, _to_display(dlg.result)))
            self._status(f"Изменён ключ «{key}»  |  Нажмите «Применить» для сохранения в файл.")

    def _delete_selected(self) -> None:
        """Remove the selected row from the in-memory entries and the table.

        The file is NOT modified until the user clicks «Применить».
        """
        item = self._tree.focus()
        if not item:
            messagebox.showinfo("Удаление", "Сначала выберите строку в таблице.")
            return
        key = item  # iid == key
        if not messagebox.askyesno(
            "Удалить запись",
            f"Удалить ключ «{key}»?\n\nИзменение вступит в силу после нажатия «Применить».",
        ):
            return

        # Move focus to the next (or previous) row before deleting
        siblings = self._tree.get_children()
        idx = list(siblings).index(item)
        next_item = siblings[idx + 1] if idx + 1 < len(siblings) else (siblings[idx - 1] if idx > 0 else None)

        del self._entries[key]
        self._tree.delete(item)

        if next_item:
            self._tree.focus(next_item)
            self._tree.selection_set(next_item)

        self._update_row_count()
        self._status(f"Ключ «{key}» удалён  |  Нажмите «Применить» для сохранения в файл.")

    # ── Sorting ───────────────────────────────────────────────────────────────

    def _sort_by(self, col: str) -> None:
        if self._sort_col == col:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_col = col
            self._sort_reverse = False

        items = [(self._tree.set(iid, col), iid) for iid in self._tree.get_children()]
        items.sort(key=lambda x: x[0].lower(), reverse=self._sort_reverse)
        for rank, (_, iid) in enumerate(items):
            self._tree.move(iid, "", rank)

        arrow = " ▲" if not self._sort_reverse else " ▼"
        for c in (COL_KEY, COL_VALUE):
            self._tree.heading(c, text=c + (arrow if c == col else ""))

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _toggle_theme(self) -> None:
        self._is_dark = not self._is_dark
        theme = DARK_THEME if self._is_dark else LIGHT_THEME
        self.style.theme_use(theme)
        self._theme_btn.configure(text="☀ Светлая тема" if self._is_dark else "🌙 Тёмная тема")

    def _set_file_buttons_state(self, state: str) -> None:
        """Enable or disable the buttons that require an open file."""
        for btn in (self._btn_apply, self._btn_revert, self._btn_delete):
            btn.configure(state=state)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _update_title(self, filename: str = "", locale: str = "") -> None:
        if filename:
            self.title(f"{APP_TITLE}  —  {filename}  [{locale}]")
        else:
            self.title(APP_TITLE)

    def _status(self, msg: str) -> None:
        self._status_var.set(msg)
