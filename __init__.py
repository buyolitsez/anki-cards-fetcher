"""
Cambridge / Wiktionary Fetcher: fills Anki notes from the chosen dictionary.

Flow:
- Tools → Cambridge Fetch (hotkey Ctrl+Shift+C)
- Enter a word → Fetch → choose a sense → Insert / Insert & Edit
- A new note is created with mapped fields (definition, examples, synonyms, audio, picture).
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
    action = QAction("Dictionary Fetch (Cambridge/Wiktionary)", wnd)
    action.setShortcut(QKeySequence("Ctrl+Shift+C"))
    action.triggered.connect(open_dialog)
    wnd.form.menuTools.addAction(action)

    settings_action = QAction("Dictionary Fetch — Settings", wnd)
    settings_action.triggered.connect(open_settings_dialog)
    wnd.form.menuTools.addAction(settings_action)


# Hooks & config wiring (handle different Anki API shapes)
if hasattr(gui_hooks, "main_window_did_init"):
    gui_hooks.main_window_did_init.append(on_main_window_ready)
else:
    # On older versions, register immediately if the main window already exists
    try:
        on_main_window_ready(mw)
    except Exception:
        traceback.print_exc()

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
