"""
Cambridge / Wiktionary Fetcher: заполняет карточку Anki из выбранного словаря.

Основной поток:
- меню Tools → Cambridge Fetch (можно назначить хоткей в Anki)
- диалог: ввести слово → Fetch → выбрать значение → Insert
- создаётся новая нота указанного типа, поля заполняются по мэппингу.
"""

from __future__ import annotations

import traceback

from aqt import dialogs, gui_hooks, mw
from aqt.qt import QAction, QKeySequence

from .config import ADDON_NAME, DEFAULT_CONFIG
from .ui.fetch_dialog import FetchDialog
from .ui.settings_dialog import SettingsDialog


# ----------------------------- Menu hooks -----------------------------------
def open_dialog():
    dlg = FetchDialog(mw)
    dlg.exec()


def open_settings_dialog():
    dlg = SettingsDialog(mw)
    dlg.exec()


def on_main_window_ready(mw_obj=None):
    wnd = mw_obj or mw
    action = QAction("Cambridge Fetch", wnd)
    action.setShortcut(QKeySequence("Ctrl+Shift+C"))
    action.triggered.connect(open_dialog)
    wnd.form.menuTools.addAction(action)

    settings_action = QAction("Cambridge Fetch — настройки", wnd)
    settings_action.triggered.connect(open_settings_dialog)
    wnd.form.menuTools.addAction(settings_action)


def add_toolbar_link(*args):
    """
    Добавляем кнопку в верхний тулбар Anki.
    Хук сигнатуры менялись: иногда передают (links, toolbar), иногда только toolbar.
    """
    try:
        links = None
        toolbar = None
        if len(args) == 1:
            toolbar = args[0]
            links = getattr(toolbar, "links", None)
        elif len(args) >= 2:
            links, toolbar = args[0], args[1]
        if links is None:
            return
        # Anki 23+ may use ToolbarLink dataclass; older uses tuple
        link_obj = None
        try:
            from aqt.toolbar import ToolbarLink  # type: ignore
            link_obj = ToolbarLink(
                name="cambridge_fetch",
                label="Cambridge",
                tooltip="Открыть Cambridge Fetch",
                icon=None,
            )
        except Exception:
            link_obj = ("cambridge_fetch", "Cambridge")
        links.append(link_obj)
    except Exception:
        traceback.print_exc()


def handle_toolbar_link(link, toolbar):
    if link == "cambridge_fetch":
        open_dialog()


# Hooks & config wiring (handle different Anki API shapes)
if hasattr(gui_hooks, "main_window_did_init"):
    gui_hooks.main_window_did_init.append(on_main_window_ready)
else:
    # на старых версиях добавим сразу, если окно уже есть
    try:
        on_main_window_ready(mw)
    except Exception:
        traceback.print_exc()
if hasattr(gui_hooks, "top_toolbar_did_redraw"):
    gui_hooks.top_toolbar_did_redraw.append(add_toolbar_link)
if hasattr(gui_hooks, "toolbar_did_redraw"):
    gui_hooks.toolbar_did_redraw.append(add_toolbar_link)
if hasattr(gui_hooks, "toolbar_did_receive_link"):
    gui_hooks.toolbar_did_receive_link.append(handle_toolbar_link)
if hasattr(gui_hooks, "top_toolbar_did_receive_link"):
    gui_hooks.top_toolbar_did_receive_link.append(handle_toolbar_link)

defaults_attr = getattr(mw.addonManager, "addonConfigDefaults", None)
if isinstance(defaults_attr, dict):
    defaults_attr[ADDON_NAME] = DEFAULT_CONFIG
elif callable(defaults_attr):
    try:
        defaults_attr(ADDON_NAME, DEFAULT_CONFIG)  # type: ignore[arg-type]
    except Exception:
        pass
elif hasattr(mw.addonManager, "setConfigDefaults"):
    mw.addonManager.setConfigDefaults(ADDON_NAME, DEFAULT_CONFIG)
