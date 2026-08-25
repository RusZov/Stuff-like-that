from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication, QComboBox, QGridLayout, QGroupBox, QLabel, QMainWindow,
    QPushButton, QTextEdit, QVBoxLayout, QWidget
)

from dota_data import DotaData, POSITION_POOLS
from engine import recommendations, strategy
from vision import Vision


class Worker(QThread):
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args = fn, args

    def run(self):
        try:
            result = self.fn(*self.args)
            self.done.emit(str(result))
        except Exception as exc:
            self.failed.emit(str(exc))


class Coach(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dota 2 Coach")
        self.resize(920, 780)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.data = DotaData()
        self.vision = Vision(self.data)
        self.worker: Worker | None = None

        root = QWidget(); self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        title = QLabel("DOTA 2 COACH — PICK + TACTICS")
        title.setStyleSheet("font-size:22px;font-weight:700")
        layout.addWidget(title)

        self.role = QComboBox(); self.role.addItems(POSITION_POOLS.keys())
        layout.addWidget(QLabel("Ваша позиция")); layout.addWidget(self.role)

        grid = QGridLayout()
        self.allies = [self.hero_box() for _ in range(4)]
        self.enemies = [self.hero_box() for _ in range(5)]
        for i, box in enumerate(self.allies): grid.addWidget(box, 0, i)
        for i, box in enumerate(self.enemies): grid.addWidget(box, 1, i)
        group = QGroupBox("Союзники (верх) / Враги (низ)"); group.setLayout(grid); layout.addWidget(group)

        self.out = QTextEdit(); self.out.setReadOnly(True); layout.addWidget(self.out, 1)

        self.analyze = QPushButton("АНАЛИЗИРОВАТЬ")
        self.analyze.clicked.connect(self.refresh)
        layout.addWidget(self.analyze)

        self.sync_btn = QPushButton("ОБНОВИТЬ ГЕРОЕВ + МАТЧАПЫ")
        self.sync_btn.clicked.connect(self.sync_data)
        layout.addWidget(self.sync_btn)

        self.portraits_btn = QPushButton("СКАЧАТЬ ПОРТРЕТЫ ДЛЯ РАСПОЗНАВАНИЯ")
        self.portraits_btn.clicked.connect(self.download_portraits)
        layout.addWidget(self.portraits_btn)

        self.scan_btn = QPushButton("РАСПОЗНАТЬ ГЕРОЕВ НА ЭКРАНЕ")
        self.scan_btn.clicked.connect(self.scan_once)
        layout.addWidget(self.scan_btn)

        self.status = QLabel(); layout.addWidget(self.status)
        self.update_status()
        self.refresh()

    def hero_box(self) -> QComboBox:
        box = QComboBox(); box.setEditable(True)
        box.addItem("—"); box.addItems(sorted(self.data.heroes))
        box.setCurrentIndex(0)
        return box

    def selected(self, boxes: list[QComboBox]) -> list[str]:
        valid = self.data.heroes
        return [b.currentText() for b in boxes if b.currentText() in valid]

    def update_status(self, suffix: str = ""):
        text = f"Героев: {len(self.data.heroes)} | источник: {self.data.source} | портретов: {len(self.vision.templates)}"
        if suffix:
            text += f" | {suffix}"
        self.status.setText(text)

    def refresh_boxes(self):
        names = sorted(self.data.heroes)
        for box in self.allies + self.enemies:
            old = box.currentText()
            box.blockSignals(True); box.clear(); box.addItem("—"); box.addItems(names)
            idx = box.findText(old); box.setCurrentIndex(idx if idx >= 0 else 0); box.blockSignals(False)

    def refresh(self):
        allies, enemies = self.selected(self.allies), self.selected(self.enemies)
        picks = recommendations(self.data, allies, enemies, self.role.currentText())
        text = ["ЛУЧШИЕ ПИКИ"] + [f"{i+1}. {p.hero} — {p.score:.1f}/99 — {p.why}" for i, p in enumerate(picks)]
        text += ["", strategy(self.data, allies, enemies)]
        self.out.setPlainText("\n".join(text))

    def _run(self, fn, done_message: str, *args):
        if self.worker and self.worker.isRunning():
            self.update_status("операция уже выполняется")
            return
        self.sync_btn.setEnabled(False); self.portraits_btn.setEnabled(False)
        self.worker = Worker(fn, *args)
        self.worker.done.connect(lambda result: self._worker_done(f"{done_message}: {result}"))
        self.worker.failed.connect(lambda error: self._worker_done(f"ошибка: {error}"))
        self.worker.start()

    def _worker_done(self, message: str):
        self.sync_btn.setEnabled(True); self.portraits_btn.setEnabled(True)
        self.vision = Vision(self.data)
        self.refresh_boxes(); self.refresh(); self.update_status(message)

    def sync_data(self):
        enemies = self.selected(self.enemies)
        def task():
            count = self.data.sync_heroes()
            matchups = self.data.sync_matchups(enemies) if enemies else 0
            return f"{count} героев, matchup-пакетов: {matchups}"
        self._run(task, "синхронизация завершена")

    def download_portraits(self):
        self._run(lambda: self.data.download_portraits(), "портреты загружены")

    def scan_once(self):
        try:
            found = self.vision.detect(self.vision.screenshot())
            self.update_status("на экране: " + (", ".join(found[:15]) if found else "ничего не распознано"))
        except Exception as exc:
            self.update_status(f"ошибка захвата: {exc}")


def main():
    app = QApplication(sys.argv)
    pal = app.palette()
    pal.setColor(QPalette.Window, QColor(20, 24, 31)); pal.setColor(QPalette.WindowText, Qt.white)
    pal.setColor(QPalette.Base, QColor(28, 33, 42)); pal.setColor(QPalette.Text, Qt.white)
    app.setPalette(pal)
    w = Coach(); w.show(); sys.exit(app.exec())

if __name__ == "__main__":
    main()
