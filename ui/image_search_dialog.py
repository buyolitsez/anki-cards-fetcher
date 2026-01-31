from __future__ import annotations

import traceback
from typing import List, Optional

from aqt import mw
from aqt.qt import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSize,
    QVBoxLayout,
    Qt,
)
from aqt.utils import showWarning, tooltip

from ..config import get_config
from ..image_search import ImageResult, attach_thumbnails, search_images


class ImageSearchDialog(QDialog):
    def __init__(self, parent=None, query: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Image search")
        self.cfg = get_config()
        self.results: List[ImageResult] = []
        self.selected: Optional[ImageResult] = None

        # widgets
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("Search images...")
        self.query_edit.setText(query or "")
        self.search_btn = QPushButton("Search")
        self.status_label = QLabel("")

        self.results_list = QListWidget()
        self.results_list.setViewMode(QListWidget.IconMode)
        self.results_list.setIconSize(QSize(160, 160))
        self.results_list.setResizeMode(QListWidget.Adjust)
        self.results_list.setMovement(QListWidget.Static)
        self.results_list.setSpacing(8)
        self.results_list.setSelectionMode(QListWidget.SingleSelection)

        self.use_btn = QPushButton("Use selected")
        self.cancel_btn = QPushButton("Cancel")

        # layout
        top = QHBoxLayout()
        top.addWidget(self.query_edit, 1)
        top.addWidget(self.search_btn)

        buttons = QHBoxLayout()
        buttons.addWidget(self.use_btn)
        buttons.addWidget(self.cancel_btn)

        main = QVBoxLayout()
        main.addLayout(top)
        main.addWidget(self.status_label)
        main.addWidget(self.results_list, 1)
        main.addLayout(buttons)
        self.setLayout(main)

        # signals
        self.search_btn.clicked.connect(self.on_search)
        self.query_edit.returnPressed.connect(self.on_search)
        self.results_list.itemDoubleClicked.connect(lambda _: self.accept_selected())
        self.use_btn.clicked.connect(self.accept_selected)
        self.cancel_btn.clicked.connect(self.reject)

        if self.query_edit.text().strip():
            self.on_search()

    def accept_selected(self):
        item = self.results_list.currentItem()
        if not item:
            showWarning("Select an image first.")
            return
        res = item.data(Qt.UserRole)
        if not isinstance(res, ImageResult):
            showWarning("Invalid selection.")
            return
        self.selected = res
        self.accept()

    def on_search(self):
        query = self.query_edit.text().strip()
        if not query:
            showWarning("Enter a search query.")
            return
        self._set_busy(True, f"Searching for \"{query}\"...")

        def task():
            image_cfg = self.cfg.get("image_search", {}) if isinstance(self.cfg.get("image_search"), dict) else {}
            provider = image_cfg.get("provider", "duckduckgo")
            max_results = int(image_cfg.get("max_results") or 12)
            safe = bool(image_cfg.get("safe_search", True))
            results = search_images(query, provider=provider, max_results=max_results, safe_search=safe)
            attach_thumbnails(results)
            return results

        def on_done(future):
            try:
                results = future.result()
            except Exception as e:
                self._set_busy(False, "")
                showWarning(f"Image search failed: {e}")
                traceback.print_exc()
                return
            self._set_busy(False, f"Found {len(results)} images.")
            self._show_results(results)

        self._run_in_background(task, on_done)

    def _run_in_background(self, task, on_done):
        if hasattr(mw, "taskman"):
            mw.taskman.run_in_background(task, on_done)
            return
        # fallback: run synchronously (older Anki)
        try:
            res = task()
            on_done(_DummyFuture(res, None))
        except Exception as e:
            on_done(_DummyFuture(None, e))

    def _show_results(self, results: List[ImageResult]):
        self.results = results
        self.results_list.clear()
        for res in results:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, res)
            if res.thumb_bytes:
                from aqt.qt import QIcon, QPixmap

                pix = QPixmap()
                if pix.loadFromData(res.thumb_bytes):
                    item.setIcon(QIcon(pix))
            title = res.title or res.source_url or res.image_url
            if title:
                item.setToolTip(title)
            item.setText("")
            item.setSizeHint(QSize(180, 200))
            self.results_list.addItem(item)
        if results:
            self.results_list.setCurrentRow(0)
        else:
            tooltip("No images found.", parent=self)

    def _set_busy(self, busy: bool, text: str):
        self.search_btn.setEnabled(not busy)
        self.use_btn.setEnabled(not busy)
        self.results_list.setEnabled(not busy)
        self.status_label.setText(text)


class _DummyFuture:
    def __init__(self, value, exc: Optional[Exception]):
        self._value = value
        self._exc = exc

    def result(self):
        if self._exc:
            raise self._exc
        return self._value
