from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from dota_data import DotaData


class Vision:
    """Read-only screen recognizer. It never reads Dota memory and never sends input to the game."""
    def __init__(self, data: DotaData, template_dir: Path | str = "assets/heroes") -> None:
        self.data = data
        self.template_dir = Path(template_dir)
        self.templates: dict[str, np.ndarray] = {}
        self.reload()

    def reload(self) -> None:
        self.templates.clear()
        slug_to_name = {hero.slug: hero.name for hero in self.data.heroes.values()}
        if not self.template_dir.exists():
            return
        for path in self.template_dir.glob("*.png"):
            img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if img is None or min(img.shape[:2]) < 12:
                continue
            name = slug_to_name.get(path.stem, path.stem.replace("_", " ").title())
            self.templates[name] = img

    def screenshot(self, monitor_index: int = 1) -> np.ndarray:
        import mss
        with mss.mss() as sct:
            monitors = sct.monitors
            index = monitor_index if 0 < monitor_index < len(monitors) else 1
            return np.asarray(sct.grab(monitors[index]))[:, :, :3]

    def detect(self, frame: np.ndarray, threshold: float = 0.91) -> list[str]:
        if not self.templates:
            return []
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        found: list[tuple[float, str]] = []
        for name, templ in self.templates.items():
            best = -1.0
            for scale in (0.55, 0.70, 0.85, 1.0):
                candidate = templ if scale == 1.0 else cv2.resize(templ, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                h, w = candidate.shape[:2]
                if h > gray.shape[0] or w > gray.shape[1] or h < 10 or w < 10:
                    continue
                result = cv2.matchTemplate(gray, candidate, cv2.TM_CCOEFF_NORMED)
                best = max(best, float(result.max()))
            if best >= threshold:
                found.append((best, name))
        found.sort(reverse=True)
        return [name for _, name in found]
