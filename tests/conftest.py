from __future__ import annotations

import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
# Add parent of addon root so we can import package by folder name
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

# Stub minimal aqt.mw for config imports outside Anki
if "aqt" not in sys.modules:
    aqt = types.ModuleType("aqt")

    class _DummyAddonManager:
        def addonFromModule(self, _name):
            raise Exception("no addon manager in tests")

        def getConfig(self, _name):
            return {}

        def writeConfig(self, _name, _cfg):
            return None

    class _DummyMW:
        addonManager = _DummyAddonManager()

    # minimal gui_hooks with main_window_did_init list to avoid immediate hook calls
    aqt.gui_hooks = types.SimpleNamespace(main_window_did_init=[])
    aqt.dialogs = types.SimpleNamespace()
    aqt.mw = _DummyMW()
    sys.modules["aqt"] = aqt

# Stub aqt.qt module for QAction/QKeySequence imports
if "aqt.qt" not in sys.modules:
    qt = types.ModuleType("aqt.qt")

    class _DummySignal:
        def connect(self, *_args, **_kwargs):
            return None

    class _Dummy:
        def __init__(self, *args, **kwargs):
            self.triggered = _DummySignal()
            pass

        def setShortcut(self, *_args, **_kwargs):
            return None

    qt.QAction = _Dummy
    qt.QKeySequence = _Dummy
    sys.modules["aqt.qt"] = qt
