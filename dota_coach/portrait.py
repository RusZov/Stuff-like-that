from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable
from urllib.request import Request, urlopen

from .data import Hero

if TYPE_CHECKING:
    import numpy as np
    from PIL import Image

STEAM_CDN_BASE = "https://cdn.cloudflare.steamstatic.com"


class PortraitDependencyError(RuntimeError):
    """Raised when optional portrait-recognition dependencies are unavailable."""


class PortraitIndexError(RuntimeError):
    """Raised when a portrait index cannot classify an input safely."""


def _vision_deps() -> tuple[Any, Any, Any]:
    try:
        import numpy as np
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover - exercised on minimal installs
        raise PortraitDependencyError(
            "Portrait recognition requires the optional vision dependencies. "
            "Install with: pip install -e '.[vision]'"
        ) from exc
    return np, Image, ImageOps


def hero_portrait_url(hero: Hero) -> str | None:
    """Resolve OpenDota's portrait path to the Steam CDN used by Dota assets."""
    path = hero.portrait_path
    if not path:
        return None
    if path.startswith("https://") or path.startswith("http://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return STEAM_CDN_BASE + path


def download_reference_portraits(
    heroes: Iterable[Hero],
    directory: str | Path,
    *,
    overwrite: bool = False,
    timeout: float = 15.0,
) -> tuple[dict[int, Path], dict[int, str]]:
    """Download canonical hero portraits for the stable draft-HUD classifier.

    Files are keyed by hero id so renamed/localized heroes do not break the cache.
    Individual failures are returned instead of aborting the complete reference set.
    """
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    saved: dict[int, Path] = {}
    errors: dict[int, str] = {}

    for hero in heroes:
        url = hero_portrait_url(hero)
        if not url:
            errors[hero.id] = "missing portrait path"
            continue
        path = target / f"{hero.id}.png"
        if path.exists() and not overwrite:
            saved[hero.id] = path
            continue
        request = Request(
            url,
            headers={
                "User-Agent": "DotaCoachMVP (+https://github.com/RusZov/Stuff-like-that)",
                "Accept": "image/*",
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = response.read()
            if not payload:
                raise ValueError("empty image response")
            path.write_bytes(payload)
            saved[hero.id] = path
        except Exception as exc:  # one broken CDN asset must not poison the batch
            errors[hero.id] = str(exc)

    return saved, errors


def _as_rgb_image(image: Any) -> Any:
    np, Image, _ImageOps = _vision_deps()
    if isinstance(image, Image.Image):
        return image.convert("RGB")
    if isinstance(image, (str, Path)):
        with Image.open(image) as opened:
            return opened.convert("RGB")
    if isinstance(image, (bytes, bytearray, memoryview)):
        with Image.open(BytesIO(bytes(image))) as opened:
            return opened.convert("RGB")
    if isinstance(image, np.ndarray):
        array = image
        if array.ndim != 3 or array.shape[2] not in (3, 4):
            raise PortraitIndexError("numpy portrait input must be HxWx3 or HxWx4")
        if array.dtype != np.uint8:
            array = np.clip(array, 0, 255).astype(np.uint8)
        if array.shape[2] == 4:
            array = array[:, :, :3]
        return Image.fromarray(array, mode="RGB")
    raise PortraitIndexError(f"Unsupported portrait image type: {type(image).__name__}")


def _grid_means(array: Any, rows: int, cols: int) -> Any:
    np, _Image, _ImageOps = _vision_deps()
    height, width = array.shape[:2]
    features: list[Any] = []
    for row in range(rows):
        y0 = round(row * height / rows)
        y1 = round((row + 1) * height / rows)
        for col in range(cols):
            x0 = round(col * width / cols)
            x1 = round((col + 1) * width / cols)
            cell = array[y0:y1, x0:x1]
            if cell.size == 0:
                features.append(np.zeros(array.shape[2:] or (1,), dtype=np.float32))
            else:
                features.append(cell.mean(axis=(0, 1)) if cell.ndim == 3 else np.array([cell.mean()]))
    return np.concatenate([np.asarray(value, dtype=np.float32).reshape(-1) for value in features])


def portrait_embedding(image: Any) -> Any:
    """Build a compact embedding for a *known portrait crop*, not a world scene.

    The descriptor mixes blockwise chroma, normalized luminance structure and
    edge energy. It is deliberately brightness-tolerant and does not slide a
    template over the frame. DraftLayout is responsible for producing the ROI.
    """
    np, _Image, ImageOps = _vision_deps()
    rgb = _as_rgb_image(image)
    # OpenDota hero portraits are wide. Fit rather than stretch so an ROI with a
    # slightly different aspect ratio does not distort facial/armor structure.
    rgb = ImageOps.fit(rgb, (96, 54), method=ImageOps.Resampling.LANCZOS, centering=(0.5, 0.5))
    array = np.asarray(rgb, dtype=np.float32) / 255.0

    # Chroma is much less sensitive to brightness changes than raw RGB.
    channel_sum = array.sum(axis=2, keepdims=True)
    chroma = array / np.maximum(channel_sum, 1e-4)
    chroma_grid = _grid_means(chroma, 4, 6)

    luminance = 0.2126 * array[:, :, 0] + 0.7152 * array[:, :, 1] + 0.0722 * array[:, :, 2]
    lum_mean = float(luminance.mean())
    lum_std = float(luminance.std())
    normalized_lum = (luminance - lum_mean) / max(lum_std, 0.04)
    lum_grid = _grid_means(normalized_lum[:, :, None], 4, 6)

    gx = np.zeros_like(normalized_lum)
    gy = np.zeros_like(normalized_lum)
    gx[:, 1:-1] = normalized_lum[:, 2:] - normalized_lum[:, :-2]
    gy[1:-1, :] = normalized_lum[2:, :] - normalized_lum[:-2, :]
    edge = np.sqrt(gx * gx + gy * gy)
    edge_grid = _grid_means(edge[:, :, None], 4, 6)

    feature = np.concatenate((chroma_grid * 1.35, lum_grid * 0.75, edge_grid * 0.55)).astype(np.float32)
    feature -= feature.mean()
    norm = float(np.linalg.norm(feature))
    if not np.isfinite(norm) or norm < 1e-8:
        raise PortraitIndexError("Portrait crop has no usable visual structure")
    return feature / norm


@dataclass(frozen=True)
class PortraitMatch:
    hero_id: int
    hero_name: str
    similarity: float
    margin: float
    confidence: float
    accepted: bool


class PortraitIndex:
    """Reference embedding index for already-cropped draft portraits."""

    def __init__(self) -> None:
        self._names: dict[int, str] = {}
        self._features: dict[int, list[Any]] = {}

    @property
    def hero_count(self) -> int:
        return len(self._features)

    def add_reference(self, hero_id: int, hero_name: str, image: Any) -> None:
        if hero_id <= 0:
            raise ValueError("hero_id must be positive")
        feature = portrait_embedding(image)
        self._names[hero_id] = hero_name
        self._features.setdefault(hero_id, []).append(feature)

    @classmethod
    def from_directory(cls, heroes: Iterable[Hero], directory: str | Path) -> "PortraitIndex":
        root = Path(directory)
        index = cls()
        for hero in heroes:
            path = root / f"{hero.id}.png"
            if path.exists():
                index.add_reference(hero.id, hero.name, path)
        return index

    def classify(
        self,
        image: Any,
        *,
        min_similarity: float = 0.78,
        min_margin: float = 0.018,
        min_confidence: float = 0.58,
    ) -> PortraitMatch:
        if not self._features:
            raise PortraitIndexError("Portrait index is empty")
        np, _Image, _ImageOps = _vision_deps()
        query = portrait_embedding(image)

        ranked: list[tuple[float, int]] = []
        for hero_id, references in self._features.items():
            # Multiple references (normal portrait, crop variant, calibrated HUD
            # sample) can coexist; use the strongest reference per hero.
            similarity = max(float(np.dot(query, feature)) for feature in references)
            ranked.append((similarity, hero_id))
        ranked.sort(reverse=True)

        best_similarity, best_id = ranked[0]
        second_similarity = ranked[1][0] if len(ranked) > 1 else -1.0
        margin = best_similarity - second_similarity

        # Confidence combines absolute likeness and class separation. The exact
        # thresholds remain conservative until current 7.41e draft screenshots
        # are collected and measured; low-confidence slots must stay manual.
        likeness = max(0.0, min(1.0, (best_similarity - 0.62) / 0.38))
        separation = max(0.0, min(1.0, margin / 0.10))
        confidence = 0.68 * likeness + 0.32 * separation
        accepted = (
            best_similarity >= min_similarity
            and margin >= min_margin
            and confidence >= min_confidence
        )

        return PortraitMatch(
            hero_id=best_id,
            hero_name=self._names[best_id],
            similarity=round(best_similarity, 4),
            margin=round(margin, 4),
            confidence=round(confidence, 4),
            accepted=accepted,
        )
