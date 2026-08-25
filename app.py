from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import mss
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication, QComboBox, QGridLayout, QGroupBox, QLabel, QMainWindow,
    QPushButton, QTextEdit, QVBoxLayout, QWidget
)

HEROES = [
    "Abaddon", "Axe", "Bane", "Crystal Maiden", "Drow Ranger", "Earthshaker",
    "Invoker", "Juggernaut", "Lion", "Magnus", "Mars", "Puck", "Pudge",
    "Shadow Fiend", "Sniper", "Sven", "Tidehunter", "Timbersaw", "Tiny",
    "Viper", "Void Spirit", "Windranger", "Witch Doctor"
]

# MVP knowledge base. Replace/extend with patch-specific data later.
TAGS = {
    "Axe": {"initiation": 3, "tank": 3, "control": 2},
    "Crystal Maiden": {"control": 3, "magic": 3, "support": 3},
    "Earthshaker": {"initiation": 3, "control": 3, "teamfight": 3},
    "Juggernaut": {"carry": 3, "push": 2, "sustain": 1},
    "Lion": {"control": 3, "burst": 3, "support": 3},
    "Magnus": {"initiation": 3, "teamfight": 3, "buff": 2},
    "Mars": {"initiation": 3, "tank": 2, "teamfight": 3},
    "Puck": {"control": 2, "mobility": 3, "magic": 2},
    "Pudge": {"pickoff": 3, "tank": 2, "control": 2},
    "Shadow Fiend": {"carry": 2, "magic": 2, "physical": 2},
    "Sniper": {"carry": 3, "range": 3, "physical": 3},
    "Sven": {"carry": 3, "physical": 3, "stun": 2},
    "Tidehunter": {"initiation": 3, "tank": 3, "teamfight": 3},
    "Timbersaw": {"tank": 2, "magic": 2, "mobility": 2},
    "Tiny": {"burst": 3, "initiation": 2, "push": 2},
    "Viper": {"lane": 3, "break": 3, "magic": 2},
    "Void Spirit": {"mobility": 3, "burst": 2, "magic": 2},
    "Windranger": {"range": 2, "control": 2, "physical": 2},
    "Witch Doctor": {"support": 3, "sustain": 2, "magic": 3},
}

COUNTERS = {
    "Sniper": {"Axe": 3, "Puck": 2, "Void Spirit": 3, "Tiny": 2},
    "Pudge": {"Viper": 2, "Timbersaw": 2, "Windranger": 1},
    "Axe": {"Timbersaw": 2, "Viper": 2, "Puck": 1},
    "Juggernaut": {"Axe": 2, "Puck": 2, "Lion": 1},
    "Tidehunter": {"Viper": 3, "Timbersaw": 1},
}

ROLE_BONUS = {
    "1 Carry": {"Juggernaut", "Sniper", "Sven", "Shadow Fiend"},
    "2 Mid": {"Puck", "Shadow Fiend", "Viper", "Void Spirit", "Tiny"},
    "3 Offlane": {"Axe", "Mars", "Tidehunter", "Timbersaw", "Magnus"},
    "4 Support": {"Earthshaker", "Lion", "Pudge", "Tiny", "Windranger"},
    "5 Hard Support": {"Crystal Maiden", "Lion", "Witch Doctor", "Bane"},
}

@dataclass
class Pick:
    hero: str
    score: float
    why: str


def score_hero(hero: str, allies: list[str], enemies: list[str], role: str) -> Pick:
    score = 50.0
    reasons = []
    if hero in ROLE_BONUS.get(role, set()):
        score += 18
        reasons.append("подходит на позицию")
    for enemy in enemies:
        value = COUNTERS.get(enemy, {}).get(hero, 0)
        if value:
            score += value * 6
            reasons.append(f"хорош против {enemy}")
    ally_tags = set()
    for ally in allies:
        ally_tags.update(TAGS.get(ally, {}))
    my_tags = TAGS.get(hero, {})
    if "teamfight" in my_tags and "initiation" not in ally_tags:
        score += 5
        reasons.append("усиливает командные драки")
    if "control" in my_tags and "control" not in ally_tags:
        score += 5
        reasons.append("добавляет контроль")
    if "tank" in my_tags and "tank" not in ally_tags:
        score += 4
        reasons.append("даёт фронтлейн")
    return Pick(hero, min(score, 99), ", ".join(reasons[:3]) or "универсальный вариант")


def recommendations(allies: list[str], enemies: list[str], role: str) -> list[Pick]:
    unavailable = set(allies + enemies)
    pool = [h for h in HEROES if h not in unavailable]
    return sorted((score_hero(h, allies, enemies, role) for h in pool), key=lambda x: x.score, reverse=True)[:5]


def strategy(allies: list[str], enemies: list[str]) -> str:
    enemy_tags = {t for h in enemies for t in TAGS.get(h, {})}
    ally_tags = {t for h in allies for t in TAGS.get(h, {})}
    lines = ["ТАКТИКА НА МАТЧ"]
    if "teamfight" in ally_tags:
        lines.append("• Играйте вокруг ключевых командных ультимейтов; не начинайте драку без них.")
    if "pickoff" in ally_tags or "control" in ally_tags:
        lines.append("• Перед объектами ищите одиночную цель через smoke/контроль.")
    if "burst" in enemy_tags or "magic" in enemy_tags:
        lines.append("• Против магического burst приоритет — защитные предметы/BKB по ситуации.")
    if "range" in enemy_tags:
        lines.append("• Не затягивайте фронтальную драку: сокращайте дистанцию до дальнего core.")
    if "carry" in enemy_tags:
        lines.append("• В драке держите контроль для вражеского core и не тратьте всё в танка.")
    lines += [
        "• После выигранной драки конвертируйте преимущество в башню или Roshan, а не в лишнюю погоню.",
        "• Подсказки основаны только на видимой/введённой информации и не управляют игрой."
    ]
    return "\n".join(lines)


class Vision:
    """Template matcher for visible draft portraits. Put legally obtained templates in assets/heroes/*.png."""
    def __init__(self):
        self.templates: dict[str, np.ndarray] = {}
        root = Path("assets/heroes")
        if root.exists():
            for path in root.glob("*.png"):
                img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    self.templates[path.stem.replace("_", " ").title()] = img

    def screenshot(self) -> np.ndarray:
        with mss.mss() as sct:
            mon = sct.monitors[1]
            return np.asarray(sct.grab(mon))[:, :, :3]

    def detect(self, frame: np.ndarray, threshold: float = 0.90) -> list[str]:
        if not self.templates:
            return []
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        found = []
        for name, templ in self.templates.items():
            if templ.shape[0] > gray.shape[0] or templ.shape[1] > gray.shape[1]:
                continue
            result = cv2.matchTemplate(gray, templ, cv2.TM_CCOEFF_NORMED)
            if float(result.max()) >= threshold:
                found.append(name)
        return found


class Coach(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dota 2 Coach MVP")
        self.resize(760, 720)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.vision = Vision()
        self.live = False

        root = QWidget(); self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        title = QLabel("DOTA 2 COACH — PICK + TACTICS")
        title.setStyleSheet("font-size:22px;font-weight:700")
        layout.addWidget(title)

        self.role = QComboBox(); self.role.addItems(ROLE_BONUS.keys())
        layout.addWidget(QLabel("Ваша позиция")); layout.addWidget(self.role)

        grid = QGridLayout()
        self.allies = [self.hero_box("—") for _ in range(4)]
        self.enemies = [self.hero_box("—") for _ in range(5)]
        for i, box in enumerate(self.allies): grid.addWidget(box, 0, i)
        for i, box in enumerate(self.enemies): grid.addWidget(box, 1, i)
        group = QGroupBox("Союзники (верх) / Враги (низ)"); group.setLayout(grid); layout.addWidget(group)

        self.out = QTextEdit(); self.out.setReadOnly(True); layout.addWidget(self.out, 1)
        self.analyze = QPushButton("АНАЛИЗИРОВАТЬ"); self.analyze.clicked.connect(self.refresh); layout.addWidget(self.analyze)
        self.live_btn = QPushButton("ВКЛЮЧИТЬ РАСПОЗНАВАНИЕ ЭКРАНА"); self.live_btn.clicked.connect(self.toggle_live); layout.addWidget(self.live_btn)
        self.status = QLabel("Vision templates: %d" % len(self.vision.templates)); layout.addWidget(self.status)

        self.timer = QTimer(self); self.timer.timeout.connect(self.scan); self.timer.setInterval(1500)
        self.refresh()

    def hero_box(self, first: str) -> QComboBox:
        box = QComboBox(); box.addItem(first); box.addItems(HEROES); return box

    def selected(self, boxes: list[QComboBox]) -> list[str]:
        return [b.currentText() for b in boxes if b.currentText() != "—"]

    def refresh(self):
        allies, enemies = self.selected(self.allies), self.selected(self.enemies)
        picks = recommendations(allies, enemies, self.role.currentText())
        text = ["ЛУЧШИЕ ПИКИ"] + [f"{i+1}. {p.hero} — {p.score:.0f}/99 — {p.why}" for i,p in enumerate(picks)]
        text += ["", strategy(allies, enemies)]
        self.out.setPlainText("\n".join(text))

    def toggle_live(self):
        self.live = not self.live
        if self.live: self.timer.start()
        else: self.timer.stop()
        self.live_btn.setText("ВЫКЛЮЧИТЬ РАСПОЗНАВАНИЕ" if self.live else "ВКЛЮЧИТЬ РАСПОЗНАВАНИЕ ЭКРАНА")

    def scan(self):
        try:
            found = self.vision.detect(self.vision.screenshot())
            self.status.setText("На экране распознано: " + (", ".join(found) if found else "ничего"))
        except Exception as e:
            self.status.setText(f"Ошибка захвата: {e}")


def main():
    app = QApplication(sys.argv)
    pal = app.palette(); pal.setColor(QPalette.Window, QColor(20, 24, 31)); pal.setColor(QPalette.WindowText, Qt.white)
    pal.setColor(QPalette.Base, QColor(28, 33, 42)); pal.setColor(QPalette.Text, Qt.white); app.setPalette(pal)
    w = Coach(); w.show(); sys.exit(app.exec())

if __name__ == "__main__":
    main()
