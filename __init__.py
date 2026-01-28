from aqt import mw
from aqt.qt import QAction
from aqt.utils import showInfo

def on_click():
    showInfo("Hello from my add-on!")

action = QAction("My Add-on: Hello", mw)
action.triggered.connect(on_click)
mw.form.menuTools.addAction(action)
