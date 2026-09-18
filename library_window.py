"""
Screenshot Library — browse, search (OCR), tag, and manage past captures.
"""
import os
import json
import datetime
from pathlib import Path
from typing import Optional, List, Dict

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QScrollArea, QLabel, QGridLayout, QFrame, QSizePolicy,
    QMessageBox, QFileDialog, QComboBox,
)
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QIcon, QImage, QColor

from PIL import Image

import config as cfg
import ai_engine as ai
import share_manager as sm

THUMB_SIZE = 180
PANEL_BG = "#16213e"
DARK_BG = "#1a1a2e"
ACCENT2 = "#00d9a3"
TEXT_FG = "#eaeaea"
TOOL_BTN = "#1f3a6b"


def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qi = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qi)


class ThumbnailCard(QFrame):
    clicked = pyqtSignal(str)  # emits file path

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path
        self.setFixedSize(THUMB_SIZE + 16, THUMB_SIZE + 52)
        self.setStyleSheet(f"""
            QFrame {{ background: {PANEL_BG}; border-radius: 8px; border: 2px solid transparent; }}
            QFrame:hover {{ border-color: {ACCENT2}; }}
        """)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self._thumb_label = QLabel()
        self._thumb_label.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_label.setStyleSheet("background: #0d1117; border-radius: 4px;")
        layout.addWidget(self._thumb_label)

        name = Path(path).name
        if len(name) > 22:
            name = name[:19] + "…"
        name_label = QLabel(name)
        name_label.setStyleSheet(f"color: {TEXT_FG}; font-size: 10px;")
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name_label)

        mtime = os.path.getmtime(path)
        dt = datetime.datetime.fromtimestamp(mtime).strftime("%d/%m %H:%M")
        date_label = QLabel(dt)
        date_label.setStyleSheet("color: #888; font-size: 9px;")
        date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(date_label)

        self._load_thumb()

    def _load_thumb(self):
        try:
            img = Image.open(self.path)
            img.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
            self._thumb_label.setPixmap(pil_to_qpixmap(img))
        except Exception:
            self._thumb_label.setText("?")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.path)
        super().mousePressEvent(e)


class OCRIndexWorker(QThread):
    """Background worker that builds OCR text index for all images."""
    progress = pyqtSignal(str, str)  # (path, ocr_text)
    done = pyqtSignal()

    def __init__(self, paths: List[str], index: Dict[str, str]):
        super().__init__()
        self.paths = paths
        self.existing_index = index

    def run(self):
        for p in self.paths:
            if p not in self.existing_index:
                try:
                    img = Image.open(p)
                    text = ai.ocr_extract_text(img)
                    self.progress.emit(p, text)
                except Exception:
                    pass
        self.done.emit()


class LibraryWindow(QWidget):
    open_in_editor = pyqtSignal(str)  # emits path to open in editor

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SnapCap — Screenshot Library")
        self.resize(1100, 700)
        self._conf = cfg.load()
        self._save_dir = Path(self._conf["save_dir"])
        self._index_file = cfg.CONFIG_DIR / "ocr_index.json"
        self._ocr_index: Dict[str, str] = self._load_index()
        self._all_paths: List[str] = []
        self._filtered_paths: List[str] = []
        self._cards: List[ThumbnailCard] = []
        self._selected_path: Optional[str] = None

        self._apply_style()
        self._build_ui()
        self._refresh_files()
        QTimer.singleShot(1000, self._start_ocr_index)

    def _apply_style(self):
        self.setStyleSheet(f"""
            QWidget {{ background: {DARK_BG}; color: {TEXT_FG}; font-family: 'Segoe UI'; font-size: 13px; }}
            QPushButton {{
                background: {TOOL_BTN}; border: none; border-radius: 6px;
                padding: 6px 14px; color: {TEXT_FG};
            }}
            QPushButton:hover {{ background: #3b82f6; }}
            QPushButton#accent {{ background: {ACCENT2}; color: #1a1a2e; font-weight: bold; }}
            QLineEdit {{ background: {PANEL_BG}; border: 1px solid {TOOL_BTN}; border-radius: 6px; padding: 6px 10px; color: {TEXT_FG}; }}
            QScrollArea {{ border: none; }}
            QFrame#card {{ background: {PANEL_BG}; border-radius: 8px; }}
            QComboBox {{ background: {PANEL_BG}; border: 1px solid {TOOL_BTN}; border-radius: 4px; padding: 4px 8px; color: {TEXT_FG}; }}
        """)

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Grid area
        left = QWidget()
        left.setStyleSheet(f"background: {DARK_BG};")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)

        # Toolbar
        toolbar = QHBoxLayout()
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("🔍  Search screenshots… (searches file names and OCR text)")
        self._search_box.textChanged.connect(self._on_search)
        toolbar.addWidget(self._search_box)

        sort_cb = QComboBox()
        sort_cb.addItems(["Newest first", "Oldest first", "Largest first", "A–Z"])
        sort_cb.currentIndexChanged.connect(lambda i: self._sort_by(i))
        toolbar.addWidget(sort_cb)

        refresh_btn = QPushButton("↺ Refresh")
        refresh_btn.clicked.connect(self._refresh_files)
        toolbar.addWidget(refresh_btn)

        open_folder_btn = QPushButton("📂 Open Folder")
        open_folder_btn.clicked.connect(self._open_folder)
        toolbar.addWidget(open_folder_btn)

        left_layout.addLayout(toolbar)

        self._count_label = QLabel()
        self._count_label.setStyleSheet("color: #888; font-size: 11px;")
        left_layout.addWidget(self._count_label)

        # Grid
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._grid_container = QWidget()
        self._grid = QGridLayout(self._grid_container)
        self._grid.setSpacing(12)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._scroll.setWidget(self._grid_container)
        left_layout.addWidget(self._scroll)

        layout.addWidget(left, 1)

        # Right panel (preview + actions)
        right = QWidget()
        right.setFixedWidth(260)
        right.setStyleSheet(f"background: {PANEL_BG};")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(8)

        right_layout.addWidget(QLabel("Preview"))
        self._preview_label = QLabel()
        self._preview_label.setFixedSize(236, 160)
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setStyleSheet("background: #0d1117; border-radius: 6px;")
        right_layout.addWidget(self._preview_label)

        self._info_label = QLabel("Select a screenshot")
        self._info_label.setWordWrap(True)
        self._info_label.setStyleSheet("color: #aaa; font-size: 11px;")
        right_layout.addWidget(self._info_label)

        for label, fn in [
            ("✏  Open in Editor", self._open_editor),
            ("📋  Copy to Clipboard", self._copy_selected),
            ("📤  Upload to Imgur", self._upload_selected),
            ("🔍  OCR Extract Text", self._ocr_selected),
            ("🗑  Delete", self._delete_selected),
        ]:
            btn = QPushButton(label)
            if "Delete" in label:
                btn.setStyleSheet(f"color: {ACCENT2};")
            btn.clicked.connect(fn)
            right_layout.addWidget(btn)

        right_layout.addStretch()

        self._ocr_status = QLabel("⏳ Building search index…")
        self._ocr_status.setStyleSheet("color: #888; font-size: 10px;")
        self._ocr_status.setWordWrap(True)
        right_layout.addWidget(self._ocr_status)

        layout.addWidget(right)

    def _load_index(self) -> Dict[str, str]:
        try:
            if self._index_file.exists():
                return json.loads(self._index_file.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_index(self):
        try:
            self._index_file.write_text(
                json.dumps(self._ocr_index, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _refresh_files(self):
        exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        self._all_paths = sorted(
            [str(p) for p in self._save_dir.rglob("*") if p.suffix.lower() in exts],
            key=os.path.getmtime, reverse=True,
        )
        self._filtered_paths = list(self._all_paths)
        self._render_grid()

    def _render_grid(self):
        # Clear existing
        for card in self._cards:
            card.setParent(None)
        self._cards.clear()

        cols = max(1, (self._scroll.width() - 20) // (THUMB_SIZE + 28))
        for i, path in enumerate(self._filtered_paths[:200]):  # limit for perf
            card = ThumbnailCard(path)
            card.clicked.connect(self._on_card_clicked)
            self._grid.addWidget(card, i // cols, i % cols)
            self._cards.append(card)

        n = len(self._filtered_paths)
        total = len(self._all_paths)
        self._count_label.setText(
            f"  {n} screenshot(s)" + (f" (filtered from {total})" if n != total else "")
        )

    def _on_search(self, query: str):
        q = query.lower().strip()
        if not q:
            self._filtered_paths = list(self._all_paths)
        else:
            self._filtered_paths = [
                p for p in self._all_paths
                if q in Path(p).name.lower()
                or q in self._ocr_index.get(p, "").lower()
            ]
        self._render_grid()

    def _sort_by(self, idx: int):
        if idx == 0:
            self._all_paths.sort(key=os.path.getmtime, reverse=True)
        elif idx == 1:
            self._all_paths.sort(key=os.path.getmtime)
        elif idx == 2:
            self._all_paths.sort(key=os.path.getsize, reverse=True)
        elif idx == 3:
            self._all_paths.sort(key=lambda p: Path(p).name.lower())
        self._on_search(self._search_box.text())

    def _on_card_clicked(self, path: str):
        self._selected_path = path
        try:
            img = Image.open(path)
            img.thumbnail((236, 160), Image.LANCZOS)
            from PyQt6.QtGui import QImage, QPixmap
            img2 = img.convert("RGBA")
            qi = QImage(img2.tobytes("raw", "RGBA"), img2.width, img2.height, QImage.Format.Format_RGBA8888)
            self._preview_label.setPixmap(QPixmap.fromImage(qi))

            size = os.path.getsize(path)
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path))
            orig = Image.open(path)
            info = (f"📐 {orig.width} × {orig.height} px\n"
                    f"💾 {size // 1024} KB\n"
                    f"🕐 {mtime.strftime('%d/%m/%Y %H:%M')}\n"
                    f"📄 {Path(path).name}")
            self._info_label.setText(info)
        except Exception as e:
            self._info_label.setText(str(e))

    def _require_selection(self) -> Optional[str]:
        if not self._selected_path:
            QMessageBox.information(self, "SnapCap", "Select a screenshot first.")
        return self._selected_path

    def _open_editor(self):
        p = self._require_selection()
        if p:
            self.open_in_editor.emit(p)

    def _copy_selected(self):
        p = self._require_selection()
        if p:
            img = Image.open(p)
            sm.copy_to_clipboard(img)

    def _upload_selected(self):
        p = self._require_selection()
        if not p:
            return
        cid = self._conf.get("upload_targets", {}).get("imgur", {}).get("client_id", "")
        if not cid:
            QMessageBox.warning(self, "Imgur", "Set Imgur Client ID in Settings.")
            return
        img = Image.open(p)
        url = sm.upload_imgur(img, cid)
        if url:
            import pyperclip
            pyperclip.copy(url)
            QMessageBox.information(self, "Imgur", f"Uploaded!\n{url}")
        else:
            QMessageBox.critical(self, "Error", "Upload failed.")

    def _ocr_selected(self):
        p = self._require_selection()
        if not p:
            return
        img = Image.open(p)
        text = ai.ocr_extract_text(img)
        from PyQt6.QtWidgets import QDialog, QTextEdit
        dlg = QDialog(self)
        dlg.setWindowTitle("OCR Result")
        dlg.resize(500, 400)
        dlg.setStyleSheet(self.styleSheet())
        vl = QVBoxLayout(dlg)
        te = QTextEdit()
        te.setPlainText(text)
        vl.addWidget(te)
        close = QPushButton("Close")
        close.clicked.connect(dlg.accept)
        vl.addWidget(close)
        dlg.exec()

    def _delete_selected(self):
        p = self._require_selection()
        if not p:
            return
        reply = QMessageBox.question(
            self, "Delete", f"Delete {Path(p).name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.remove(p)
                if p in self._ocr_index:
                    del self._ocr_index[p]
                    self._save_index()
                self._selected_path = None
                self._preview_label.clear()
                self._info_label.setText("Select a screenshot")
                self._refresh_files()
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def _open_folder(self):
        sm.open_in_explorer(str(self._save_dir / "placeholder"))

    def _start_ocr_index(self):
        missing = [p for p in self._all_paths if p not in self._ocr_index]
        if not missing:
            self._ocr_status.setText(f"✅ Search index: {len(self._ocr_index)} images")
            return
        self._worker = OCRIndexWorker(missing, self._ocr_index)
        self._worker.progress.connect(self._on_ocr_progress)
        self._worker.done.connect(self._on_ocr_done)
        self._worker.start()

    def _on_ocr_progress(self, path: str, text: str):
        self._ocr_index[path] = text
        indexed = len(self._ocr_index)
        total = len(self._all_paths)
        self._ocr_status.setText(f"🔍 Indexing {indexed}/{total}…")

    def _on_ocr_done(self):
        self._save_index()
        self._ocr_status.setText(f"✅ Index complete: {len(self._ocr_index)} images searchable")
