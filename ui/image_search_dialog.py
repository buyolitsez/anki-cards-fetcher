from __future__ import annotations

import traceback
from typing import List, Optional

from aqt import mw
from aqt.qt import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListView,
    QListWidgetItem,
    QPushButton,
    QComboBox,
    QSize,
    QVBoxLayout,
    QTimer,
    Qt,
)
from aqt.utils import showWarning, tooltip

from ..config import get_config, save_config
from ..image_search import (
    DEFAULT_IMAGE_PROVIDER,
    ImageResult,
    attach_thumbnails,
    get_image_provider_choices,
    search_images,
)


class ImageSearchDialog(QDialog):
    def __init__(self, parent=None, query: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Image search")
        self.cfg = get_config()
        self.results: List[ImageResult] = []
        self.selected: Optional[ImageResult] = None
        self.last_query: str = ""
        self.last_provider: str = ""
        self.last_safe: bool = True
        self._search_token: int = 0
        self._search_in_progress: bool = False
        self._load_token: int = 0
        self._load_in_progress: bool = False
        self._thumb_queue: List[ImageResult] = []
        self._thumb_token: int = 0
        self._thumb_in_flight: int = 0
        self._thumb_max_in_flight: int = 4

        # widgets
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("Search images...")
        self.query_edit.setText(query or "")
        self.search_btn = QPushButton("Search")
        self.provider_combo = QComboBox()
        self._populate_providers()
        self.status_label = QLabel("")

        self.results_list = QListWidget()
        view_mode = getattr(QListView, "IconMode", None)
        if view_mode is None and hasattr(QListView, "ViewMode"):
            view_mode = QListView.ViewMode.IconMode
        if view_mode is not None:
            self.results_list.setViewMode(view_mode)
        self.results_list.setIconSize(QSize(160, 160))
        resize_mode = getattr(QListView, "Adjust", None)
        if resize_mode is None and hasattr(QListView, "ResizeMode"):
            resize_mode = QListView.ResizeMode.Adjust
        if resize_mode is not None:
            self.results_list.setResizeMode(resize_mode)
        movement = getattr(QListView, "Static", None)
        if movement is None and hasattr(QListView, "Movement"):
            movement = QListView.Movement.Static
        if movement is not None:
            self.results_list.setMovement(movement)
        self.results_list.setSpacing(8)
        selection_mode = getattr(QAbstractItemView, "SingleSelection", None)
        if selection_mode is None and hasattr(QAbstractItemView, "SelectionMode"):
            selection_mode = QAbstractItemView.SelectionMode.SingleSelection
        if selection_mode is not None:
            self.results_list.setSelectionMode(selection_mode)

        self.use_btn = QPushButton("Use selected")
        self.load_more_btn = QPushButton("Load more")
        self.reload_thumbs_btn = QPushButton("Reload thumbnails")
        self.cancel_btn = QPushButton("Cancel")

        # layout
        top = QHBoxLayout()
        top.addWidget(self.query_edit, 1)
        top.addWidget(self.provider_combo)
        top.addWidget(self.search_btn)

        buttons = QHBoxLayout()
        buttons.addWidget(self.use_btn)
        buttons.addWidget(self.load_more_btn)
        buttons.addWidget(self.reload_thumbs_btn)
        buttons.addWidget(self.cancel_btn)

        main = QVBoxLayout()
        main.addLayout(top)
        main.addWidget(self.status_label)
        main.addWidget(self.results_list, 1)
        main.addLayout(buttons)
        self.setLayout(main)

        # signals
        self.search_btn.clicked.connect(self.on_search)
        self.provider_combo.currentIndexChanged.connect(self.on_provider_change)
        self.query_edit.returnPressed.connect(self.on_search)
        self.results_list.itemDoubleClicked.connect(lambda _: self.accept_selected())
        self.use_btn.clicked.connect(self.accept_selected)
        self.load_more_btn.clicked.connect(self.on_load_more)
        self.reload_thumbs_btn.clicked.connect(self.on_reload_thumbs)
        self.cancel_btn.clicked.connect(self.reject)

        if self.query_edit.text().strip():
            self.on_search()

    def accept_selected(self):
        item = self.results_list.currentItem()
        if not item:
            showWarning("Select an image first.")
            return
        res = item.data(self._user_role())
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
        image_cfg = self.cfg.get("image_search", {}) if isinstance(self.cfg.get("image_search"), dict) else {}
        provider = self.provider_combo.currentData() or image_cfg.get("provider", DEFAULT_IMAGE_PROVIDER)

        self._set_busy(True, f"Searching for \"{query}\"...")
        self._search_token += 1
        token = self._search_token
        self._search_in_progress = True
        QTimer.singleShot(20000, lambda: self._on_search_timeout(token))

        def task():
            image_cfg = self.cfg.get("image_search", {}) if isinstance(self.cfg.get("image_search"), dict) else {}
            max_results = int(image_cfg.get("max_results") or 12)
            safe = bool(image_cfg.get("safe_search", True))
            results, used_provider, _ = search_images(
                query,
                provider=provider,
                max_results=max_results,
                safe_search=safe,
                offset=0,
                allow_fallback=False,
            )
            return results, used_provider, safe

        def on_done(future, token=token):
            if token != self._search_token:
                return
            self._search_in_progress = False
            try:
                results, used_provider, safe = future.result()
            except Exception as e:
                self._set_busy(False, "")
                showWarning(f"Image search failed: {e}")
                traceback.print_exc()
                return
            self.last_query = query
            self.last_provider = used_provider
            self.last_safe = safe
            if not results:
                self._set_busy(False, f"No images found ({used_provider}).")
            else:
                self._set_busy(False, f"Found {len(results)} images.")
            self._show_results(results)
            self._start_thumbnail_jobs(results)

        self._run_in_background(task, on_done)

    def on_load_more(self):
        if not self.last_query:
            showWarning("Run a search first.")
            return
        offset = len(self.results)
        if offset <= 0:
            showWarning("Run a search first.")
            return
        image_cfg = self.cfg.get("image_search", {}) if isinstance(self.cfg.get("image_search"), dict) else {}
        provider = self.provider_combo.currentData() or self.last_provider or image_cfg.get(
            "provider", DEFAULT_IMAGE_PROVIDER
        )
        self._set_busy(True, "Loading more images...")
        self._load_token += 1
        token = self._load_token
        self._load_in_progress = True
        QTimer.singleShot(20000, lambda: self._on_load_timeout(token))

        def task():
            image_cfg = self.cfg.get("image_search", {}) if isinstance(self.cfg.get("image_search"), dict) else {}
            max_results = int(image_cfg.get("max_results") or 12)
            results, _, _ = search_images(
                self.last_query,
                provider=provider,
                max_results=max_results,
                safe_search=self.last_safe,
                offset=offset,
                allow_fallback=False,
            )
            return results

        def on_done(future, token=token):
            if token != self._load_token:
                return
            self._load_in_progress = False
            try:
                results = future.result()
            except Exception as e:
                self._set_busy(False, "")
                showWarning(f"Load more failed: {e}")
                traceback.print_exc()
                return
            self._set_busy(False, f"Loaded {len(results)} more.")
            self._append_results(results)
            self._enqueue_thumbnails(results)

        self._run_in_background(task, on_done)

    def on_reload_thumbs(self):
        if not self.results:
            showWarning("Nothing to reload.")
            return
        self._set_busy(False, "Thumbnails refresh queued.")
        self._enqueue_thumbnails(self.results, reset=True)

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
        self.results = []
        self.results_list.clear()
        self._append_results(results)
        if self.results:
            self.results_list.setCurrentRow(0)
        else:
            tooltip("No images found.", parent=self)

    def _append_results(self, results: List[ImageResult]):
        start_idx = len(self.results)
        self.results.extend(results)
        for i, res in enumerate(results):
            item = self._make_item(res, start_idx + i)
            self.results_list.addItem(item)

    def _make_item(self, res: ImageResult, index: int) -> QListWidgetItem:
        item = QListWidgetItem()
        item.setData(self._user_role(), res)
        self._apply_icon(item, res)
        title = res.title or res.source_url or res.image_url
        if title:
            item.setToolTip(title)
        item.setText(str(index + 1))
        item.setSizeHint(QSize(180, 200))
        return item

    def _apply_icon(self, item: QListWidgetItem, res: ImageResult):
        if res.thumb_bytes:
            from aqt.qt import QIcon, QPixmap

            pix = QPixmap()
            if pix.loadFromData(res.thumb_bytes):
                item.setIcon(QIcon(pix))

    def _refresh_icons(self):
        for i in range(self.results_list.count()):
            item = self.results_list.item(i)
            res = item.data(self._user_role())
            if isinstance(res, ImageResult) and res.thumb_bytes:
                self._apply_icon(item, res)

    def _set_busy(self, busy: bool, text: str):
        self.search_btn.setEnabled(not busy)
        self.use_btn.setEnabled(not busy)
        self.load_more_btn.setEnabled(not busy)
        self.reload_thumbs_btn.setEnabled(not busy)
        self.results_list.setEnabled(not busy)
        self.status_label.setText(text)

    def _user_role(self):
        user_role = getattr(Qt, "UserRole", None)
        if user_role is None and hasattr(Qt, "ItemDataRole"):
            user_role = Qt.ItemDataRole.UserRole
        return user_role

    def _populate_providers(self):
        self.provider_combo.clear()
        for label, provider_id in get_image_provider_choices():
            self.provider_combo.addItem(label, provider_id)
        self.provider_combo.setEnabled(self.provider_combo.count() > 1)
        image_cfg = self.cfg.get("image_search", {}) if isinstance(self.cfg.get("image_search"), dict) else {}
        provider = image_cfg.get("provider", DEFAULT_IMAGE_PROVIDER)
        idx = self.provider_combo.findData(provider)
        if idx == -1:
            idx = 0
        self.provider_combo.setCurrentIndex(idx)

    def on_provider_change(self):
        provider = self.provider_combo.currentData() or DEFAULT_IMAGE_PROVIDER
        image_cfg = self.cfg.get("image_search", {}) if isinstance(self.cfg.get("image_search"), dict) else {}
        save_config({"image_search": {**image_cfg, "provider": provider}})
        self.cfg = get_config()

    def _on_search_timeout(self, token: int):
        if token != self._search_token or not self._search_in_progress:
            return
        # invalidate late results
        self._search_in_progress = False
        self._search_token += 1
        self._set_busy(False, "Search timed out.")
        showWarning("Image search timed out. Try again.")

    def _on_load_timeout(self, token: int):
        if token != self._load_token or not self._load_in_progress:
            return
        self._load_in_progress = False
        self._load_token += 1
        self._set_busy(False, "Load more timed out.")
        showWarning("Load more timed out. Try again.")

    def _start_thumbnail_jobs(self, results: List[ImageResult]):
        self._thumb_token += 1
        self._thumb_in_flight = 0
        self._thumb_queue = [r for r in results if not r.thumb_bytes]
        self._pump_thumbnail_queue(self._thumb_token)

    def _enqueue_thumbnails(self, results: List[ImageResult], reset: bool = False):
        if reset:
            self._thumb_token += 1
            self._thumb_in_flight = 0
            self._thumb_queue = []
        if self._thumb_token <= 0:
            self._thumb_token = 1
        self._thumb_queue.extend([r for r in results if not r.thumb_bytes])
        self._pump_thumbnail_queue(self._thumb_token)

    def _pump_thumbnail_queue(self, token: int):
        if token != self._thumb_token:
            return
        while self._thumb_in_flight < self._thumb_max_in_flight and self._thumb_queue:
            batch = self._thumb_queue[:1]
            del self._thumb_queue[:1]
            self._thumb_in_flight += 1

            def task(batch=batch):
                attach_thumbnails(batch)
                return batch

            def on_done(future, token=token):
                self._thumb_in_flight = max(0, self._thumb_in_flight - 1)
                if token != self._thumb_token:
                    return
                try:
                    future.result()
                except Exception:
                    pass
                self._refresh_icons()
                self._pump_thumbnail_queue(token)

            self._run_in_background(task, on_done)


class _DummyFuture:
    def __init__(self, value, exc: Optional[Exception]):
        self._value = value
        self._exc = exc

    def result(self):
        if self._exc:
            raise self._exc
        return self._value
