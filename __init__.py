"""Package entrypoint.

When imported inside Anki this registers the add-on UI.
When imported from the Telegram bot/server it stays side-effect free.
"""

from __future__ import annotations

from .logger import get_logger

logger = get_logger(__name__)

try:
    from aqt import dialogs, gui_hooks, mw
    from aqt.qt import QAction, QKeySequence

    from .config import ADDON_NAME, DEFAULT_CONFIG

    def open_dialog():
        from .ui.fetch_dialog import FetchDialog

        logger.debug("Opening FetchDialog")
        dlg = FetchDialog(mw)
        dlg.exec()


    def open_settings_dialog():
        from .ui.settings_dialog import SettingsDialog

        logger.debug("Opening SettingsDialog")
        dlg = SettingsDialog(mw)
        dlg.exec()


    def run_sync_now():
        from .anki.sync import run_manual_import

        run_manual_import(parent=mw)


    def on_main_window_ready(mw_obj=None):
        wnd = mw_obj or mw
        action = QAction("Dictionary Fetch (Cambridge/Wiktionary)", wnd)
        action.setShortcut(QKeySequence("Ctrl+Shift+C"))
        action.triggered.connect(open_dialog)
        wnd.form.menuTools.addAction(action)

        settings_action = QAction("Dictionary Fetch — Settings", wnd)
        settings_action.triggered.connect(open_settings_dialog)
        wnd.form.menuTools.addAction(settings_action)

        sync_action = QAction("Dictionary Fetch — Import Telegram Queue", wnd)
        sync_action.triggered.connect(run_sync_now)
        wnd.form.menuTools.addAction(sync_action)

        try:
            from .anki.sync import initialize_sync_hooks

            initialize_sync_hooks(wnd)
        except Exception:
            logger.exception("Failed to initialize Telegram sync hooks")
        logger.info("Add-on menu items registered")


    if hasattr(gui_hooks, "main_window_did_init"):
        gui_hooks.main_window_did_init.append(on_main_window_ready)
        logger.debug("Registered main_window_did_init hook")
    else:
        try:
            on_main_window_ready(mw)
        except Exception:
            logger.exception("Failed to register menu items on older Anki")

    defaults_attr = getattr(mw.addonManager, "addonConfigDefaults", None)
    if isinstance(defaults_attr, dict):
        defaults_attr[ADDON_NAME] = DEFAULT_CONFIG
    elif callable(defaults_attr):
        try:
            defaults_attr(ADDON_NAME, DEFAULT_CONFIG)  # type: ignore[arg-type]
        except Exception:
            logger.warning("Could not set config defaults via callable")
    elif hasattr(mw.addonManager, "setConfigDefaults"):
        mw.addonManager.setConfigDefaults(ADDON_NAME, DEFAULT_CONFIG)

    logger.info("Cambridge/Wiktionary Fetcher add-on loaded")
except Exception:
    logger.debug("Package imported outside Anki; addon hooks not registered")
