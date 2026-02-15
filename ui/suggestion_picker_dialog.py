"""Suggestion picker dialog — validates typo candidates and lets the user pick one."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Dict, List, Optional

from aqt.qt import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QTimer,
    QVBoxLayout,
)

from ..logger import get_logger

logger = get_logger(__name__)

_MAX_TYPO_CHECK_WORKERS = 8
_POLL_INTERVAL_MS = 100


class SuggestionPickerDialog(QDialog):
    def __init__(
        self,
        parent,
        word: str,
        candidates: List[str],
        validate_word: Callable[[str], bool],
        target_count: int,
    ):
        super().__init__(parent)
        self.selected_word: Optional[str] = None
        self._validate_word = validate_word
        self._target_count = max(1, int(target_count))
        self._total = len(candidates)
        self._seen: set[str] = set()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._future_to_word: Dict[Future, str] = {}
        self._checked = 0
        self._confirmed = 0
        self._finished = False

        self.setWindowTitle("Suggestions")
        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"No exact match for '{word}'.\nChecking suggestions..."))
        self.status_label = QLabel("Checking candidates...")
        layout.addWidget(self.status_label)
        self.lst = QListWidget()
        layout.addWidget(self.lst)
        btns = QHBoxLayout()
        self.use_btn = QPushButton("Try selected")
        close_btn = QPushButton("Close")
        self.use_btn.setEnabled(False)
        self.use_btn.clicked.connect(self._accept_selected)
        close_btn.clicked.connect(self.reject)
        self.lst.itemDoubleClicked.connect(lambda _: self._accept_selected())
        self.lst.currentRowChanged.connect(lambda _: self.use_btn.setEnabled(self.lst.currentItem() is not None))
        btns.addWidget(self.use_btn)
        btns.addWidget(close_btn)
        layout.addLayout(btns)
        self.setLayout(layout)

        max_workers = min(_MAX_TYPO_CHECK_WORKERS, max(3, self._target_count))
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="typo-check")
        for candidate in candidates:
            future = self._executor.submit(self._safe_validate, candidate)
            self._future_to_word[future] = candidate

        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll_futures)
        self._timer.start()
        self._update_status()

    def _safe_validate(self, candidate: str) -> bool:
        try:
            return bool(self._validate_word(candidate))
        except Exception:
            return False

    def _poll_futures(self):
        if self._finished:
            return
        done = [f for f in list(self._future_to_word.keys()) if f.done()]
        if not done:
            return
        for future in done:
            candidate = self._future_to_word.pop(future)
            self._checked += 1
            is_valid = False
            try:
                is_valid = bool(future.result())
            except Exception:
                is_valid = False
            if is_valid:
                key = candidate.casefold()
                if key not in self._seen:
                    self._seen.add(key)
                    self.lst.addItem(candidate)
                    self._confirmed += 1
                    if self.lst.count() == 1:
                        self.lst.setCurrentRow(0)
        if self._confirmed >= self._target_count:
            self._finish(cancel_pending=True)
        elif not self._future_to_word:
            self._finish(cancel_pending=False)
        self._update_status()

    def _update_status(self):
        if self._finished:
            if self._confirmed:
                self.status_label.setText(f"Ready: {self._confirmed} valid suggestions.")
            else:
                self.status_label.setText("No valid suggestions found.")
            return
        self.status_label.setText(
            f"Checking... {self._checked}/{self._total} | valid: {self._confirmed}"
        )

    def _accept_selected(self):
        item = self.lst.currentItem()
        if not item:
            return
        self.selected_word = item.text().strip()
        if not self.selected_word:
            return
        self.accept()

    def _finish(self, cancel_pending: bool):
        if self._finished:
            return
        self._finished = True
        if self._timer.isActive():
            self._timer.stop()
        self._shutdown_executor(cancel_pending=cancel_pending)

    def _shutdown_executor(self, cancel_pending: bool):
        if not self._executor:
            return
        try:
            self._executor.shutdown(wait=False, cancel_futures=cancel_pending)
        except TypeError:
            self._executor.shutdown(wait=False)
        self._executor = None

    def closeEvent(self, event):  # type: ignore[override]
        self._finish(cancel_pending=True)
        super().closeEvent(event)
