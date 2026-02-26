"""Picture preview dialog — shows a full/thumbnail image for the selected sense."""

from __future__ import annotations

import webbrowser
from typing import List, Optional
from urllib.parse import urlsplit

from aqt.qt import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPixmap,
    QPushButton,
    QVBoxLayout,
    Qt,
)
from aqt.utils import showWarning

from ..logger import get_logger
from ..media import USER_AGENT
from ..wikimedia_urls import normalize_wikimedia_image_url
from .background import run_in_background

logger = get_logger(__name__)


class PicturePreviewDialog(QDialog):
    def __init__(
        self,
        parent,
        picture_url: str,
        picture_referer: Optional[str] = None,
        picture_thumb_url: Optional[str] = None,
        picture_thumb_bytes: Optional[bytes] = None,
    ):
        super().__init__(parent)
        self.picture_url = picture_url
        self.picture_referer = picture_referer
        self.picture_thumb_url = picture_thumb_url
        self.picture_thumb_bytes = picture_thumb_bytes
        self._pixmap: Optional[QPixmap] = None

        self.setWindowTitle("Picture preview")
        self.resize(760, 560)

        self.status_label = QLabel("Loading image...")
        self.status_label.setWordWrap(True)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter if hasattr(Qt, "AlignmentFlag") else Qt.AlignCenter)
        self.image_label.setMinimumHeight(300)

        open_btn = QPushButton("Open in Browser")
        close_btn = QPushButton("Close")
        open_btn.clicked.connect(self._open_in_browser)
        close_btn.clicked.connect(self.accept)

        btns = QHBoxLayout()
        btns.addWidget(open_btn)
        btns.addStretch(1)
        btns.addWidget(close_btn)

        main = QVBoxLayout()
        main.addWidget(self.status_label)
        main.addWidget(self.image_label, 1)
        main.addLayout(btns)
        self.setLayout(main)

        self._load_picture()

    def _open_in_browser(self):
        try:
            webbrowser.open(self._resolved_url(self.picture_url))
        except Exception as e:
            showWarning(f"Cannot open browser: {e}")

    def _resolved_url(self, raw_url: Optional[str]) -> str:
        url = (raw_url or "").strip()
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            if self.picture_referer:
                ref = urlsplit(self.picture_referer)
                if ref.scheme and ref.netloc:
                    return f"{ref.scheme}://{ref.netloc}{url}"
            return "https://dictionary.cambridge.org" + url
        return url

    def _load_picture(self):
        def task():
            import requests

            errors: List[str] = []

            def try_download(url: Optional[str], referer: Optional[str], label: str):
                resolved = self._resolved_url(url)
                if not resolved:
                    return None
                headers = {
                    "User-Agent": USER_AGENT,
                    "Accept": "image/*,*/*;q=0.8",
                }
                if referer:
                    headers["Referer"] = referer
                try:
                    request_url = resolved
                    resp = requests.get(request_url, headers=headers, timeout=15)
                    if resp.status_code == 429:
                        fallback_url = normalize_wikimedia_image_url(request_url)
                        if fallback_url != request_url:
                            request_url = fallback_url
                            resp = requests.get(request_url, headers=headers, timeout=15)
                    resp.raise_for_status()
                except Exception as e:
                    errors.append(f"{label}: {e}")
                    return None
                content_type = (resp.headers.get("Content-Type") or "").strip()
                return resp.content, content_type, (getattr(resp, "url", "") or request_url)

            full = try_download(self.picture_url, self.picture_referer, "full")
            if full:
                content, content_type, resolved = full
                return content, content_type, resolved, "full"

            thumb = try_download(self.picture_thumb_url, None, "thumb")
            if thumb:
                content, content_type, resolved = thumb
                return content, content_type, resolved, "thumb"

            if self.picture_thumb_bytes:
                return self.picture_thumb_bytes, "image/*", "thumbnail-bytes", "thumb-bytes"

            msg = "; ".join(errors[:2]) if errors else "image download failed"
            raise RuntimeError(msg)

        def on_done(future):
            try:
                content, content_type, resolved_url, source_kind = future.result()
            except Exception as e:
                self.status_label.setText(f"Image load failed: {e}")
                return

            pix = QPixmap()
            if not pix.loadFromData(content):
                self.status_label.setText("Cannot decode image bytes.")
                return

            self._pixmap = pix
            self._apply_scaled_pixmap()
            size_kb = max(1, round(len(content) / 1024))
            quality = self._quality_hint(pix.width(), pix.height())
            ctype = content_type or "unknown"
            prefix = ""
            if source_kind != "full":
                prefix = "Full image blocked/unavailable. Showing thumbnail.\n"
            self.status_label.setText(
                f"{prefix}{pix.width()}x{pix.height()} px, ~{size_kb} KB, {ctype}. {quality}\n{resolved_url}"
            )

        run_in_background(task, on_done)

    def _apply_scaled_pixmap(self):
        if not self._pixmap:
            self.image_label.clear()
            return
        area = self.image_label.size()
        if area.width() <= 0 or area.height() <= 0:
            return
        mode = Qt.AspectRatioMode.KeepAspectRatio if hasattr(Qt, "AspectRatioMode") else Qt.KeepAspectRatio
        transform = Qt.TransformationMode.SmoothTransformation if hasattr(Qt, "TransformationMode") else Qt.SmoothTransformation
        scaled = self._pixmap.scaled(area, mode, transform)
        self.image_label.setPixmap(scaled)

    def resizeEvent(self, event):  # type: ignore[override]
        self._apply_scaled_pixmap()
        super().resizeEvent(event)

    def _quality_hint(self, width: int, height: int) -> str:
        if width >= 1000 and height >= 700:
            return "Quality: high."
        if width >= 600 and height >= 400:
            return "Quality: medium."
        return "Quality: low, consider replacing."
