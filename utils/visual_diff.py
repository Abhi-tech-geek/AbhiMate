"""Visual regression helpers (Feature #4).

Pure-Python pixel comparison built on Pillow. Two public entry points:

* :func:`compare_images` — returns a :class:`SimilarityResult` that tells
  the engine whether two screenshots match within a similarity threshold.
* :func:`render_diff` — writes a side-by-side artifact (baseline, actual,
  highlight) so the UI can show a diff on failure.

Why a custom similarity rather than a perceptual hash?
---------------------------------------------------------
Perceptual hashes (pHash, dHash) are great at "is this the same image"
but blur out small layout regressions. We want to catch a 4-pixel button
shift, so we operate at the pixel level. To keep cost bounded we
downscale to a common box (default 256 px on the longest side) before
diffing — that preserves layout signal while killing anti-alias noise
and being O(1)-ish per assertion.

The module fails closed: if Pillow is missing, raising
:class:`VisualDiffUnavailable` so callers can surface a friendly hint.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Optional, Tuple

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    _HAS_PIL = True
except Exception:  # pragma: no cover - exercised when Pillow missing
    _HAS_PIL = False


class VisualDiffUnavailable(RuntimeError):
    """Raised when Pillow is not installed.

    The engine catches this and surfaces a friendly install hint instead
    of a raw ImportError stacktrace.
    """


@dataclass
class SimilarityResult:
    """Outcome of a visual comparison.

    ``similarity`` is in [0.0, 1.0]; 1.0 = pixel-perfect.
    ``threshold`` is the floor below which the assertion fails.
    ``passed`` is precomputed for convenience (``similarity >= threshold``).
    ``diff_box`` is an optional bounding box ``(left, top, right, bottom)``
    around the changed pixels — useful for UI overlay rendering.
    """

    similarity: float
    threshold: float
    width: int
    height: int
    changed_pixels: int
    total_pixels: int
    diff_box: Optional[Tuple[int, int, int, int]] = None
    passed: bool = field(init=False)

    def __post_init__(self) -> None:
        # Round trip through float() to defend against the LLM emitting
        # a string like "0.95" on `expected`.
        self.similarity = float(self.similarity)
        self.threshold = float(self.threshold)
        self.passed = self.similarity >= self.threshold

    @property
    def diff_percent(self) -> float:
        return 100.0 * (1.0 - self.similarity)


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------

def compare_images(
    baseline_path: str,
    actual_path: str,
    threshold: float = 0.98,
    downscale: int = 256,
) -> SimilarityResult:
    """Compare two image files and return a SimilarityResult.

    Both images are normalised to RGB and resized to the same bounding
    box (``downscale`` is the longest-side target) so anti-alias shifts
    don't tank the score. The similarity is ``1 - mean_abs_diff/255``,
    a plain pixel-mean metric — easy to reason about, no surprises.
    """
    if not _HAS_PIL:
        raise VisualDiffUnavailable(
            "Pillow is required for visual regression. Install with: pip install Pillow"
        )
    if not os.path.exists(baseline_path):
        raise FileNotFoundError(f"Baseline image not found: {baseline_path}")
    if not os.path.exists(actual_path):
        raise FileNotFoundError(f"Actual image not found: {actual_path}")

    threshold = max(0.0, min(1.0, float(threshold)))
    target = max(32, int(downscale))

    with Image.open(baseline_path) as a_raw, Image.open(actual_path) as b_raw:
        a = _normalize(a_raw, target)
        b = _normalize(b_raw, target)
        # _normalize already aligned to the same box, but defend in depth:
        if a.size != b.size:
            b = b.resize(a.size, Image.LANCZOS)

        diff = ImageChops.difference(a, b)
        # Sum of pixel deltas across all channels.
        # Histogram gives us per-channel pixel counts at each intensity 0..255;
        # the weighted sum collapses that into one number per channel.
        hist = diff.histogram()
        # RGB → 3 channels of 256 buckets each.
        channels = len(hist) // 256
        total_pixel_pairs = a.size[0] * a.size[1]
        total_channel_pairs = total_pixel_pairs * channels

        delta_sum = 0
        changed_pixels = 0
        for c in range(channels):
            base = c * 256
            for v in range(256):
                count = hist[base + v]
                delta_sum += count * v
                if v >= 8:  # ignore tiny AA jitter
                    changed_pixels += count

        # Average channel delta normalised to [0,1].
        mean_abs = delta_sum / max(1, total_channel_pairs) / 255.0
        similarity = max(0.0, min(1.0, 1.0 - mean_abs))

        diff_box = _compute_diff_box(diff)

    return SimilarityResult(
        similarity=similarity,
        threshold=threshold,
        width=a.size[0],
        height=a.size[1],
        changed_pixels=changed_pixels // max(1, channels),
        total_pixels=total_pixel_pairs,
        diff_box=diff_box,
    )


def render_diff(
    baseline_path: str,
    actual_path: str,
    out_path: str,
    box: Optional[Tuple[int, int, int, int]] = None,
) -> str:
    """Write a side-by-side ``baseline | actual | overlay`` PNG to ``out_path``.

    The overlay panel is the actual image with a red-tinted highlight on
    every pixel that differs by more than 8 units of intensity. Returns
    the path so callers can store it on the trace.
    """
    if not _HAS_PIL:
        raise VisualDiffUnavailable(
            "Pillow is required for visual regression. Install with: pip install Pillow"
        )

    target_h = 400  # composite height; each panel scales to this
    panels = []
    with Image.open(baseline_path) as a_raw, Image.open(actual_path) as b_raw:
        a = a_raw.convert("RGBA")
        b = b_raw.convert("RGBA")
        # Resize each to the common height while preserving aspect ratio.
        a = _scale_to_height(a, target_h)
        b = _scale_to_height(b, target_h)

        # Highlight panel: take actual, overlay red where it differs.
        a_match = a.resize(b.size, Image.LANCZOS)
        diff = ImageChops.difference(a_match.convert("RGB"), b.convert("RGB"))
        mask = diff.convert("L").point(lambda px: 255 if px > 8 else 0).filter(
            ImageFilter.MaxFilter(3)
        )
        overlay = b.copy()
        red = Image.new("RGBA", b.size, (255, 64, 64, 160))
        overlay.paste(red, (0, 0), mask)

        # Draw the diff box if known.
        if box and a.size == b.size:
            scale_x = b.size[0] / max(1, a_match.size[0])
            scale_y = b.size[1] / max(1, a_match.size[1])
            l, t, r, btm = box
            scaled_box = (
                int(l * scale_x), int(t * scale_y),
                int(r * scale_x), int(btm * scale_y),
            )
            ImageDraw.Draw(overlay).rectangle(scaled_box, outline=(255, 64, 64, 255), width=3)

        panels = [a, b, overlay]

    width = sum(p.size[0] for p in panels) + 20
    composite = Image.new("RGBA", (width, target_h + 30), (18, 20, 32, 255))
    draw = ImageDraw.Draw(composite)
    x = 0
    for label, panel in zip(("baseline", "actual", "diff"), panels):
        composite.paste(panel, (x, 24))
        draw.text((x + 6, 4), label, fill=(220, 230, 245, 255))
        x += panel.size[0] + 10

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    composite.convert("RGB").save(out_path, format="PNG", optimize=True)
    return out_path


def image_sha256(path: str) -> str:
    """Stable content hash for an image — used as a sidecar fingerprint."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def image_size(path: str) -> Tuple[int, int]:
    """Best-effort (width, height) lookup. Returns (0,0) on failure."""
    if not _HAS_PIL:
        return (0, 0)
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return (0, 0)


# ---------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------

def _normalize(im, longest_side: int):
    """Convert to RGB and resize so the longest side equals ``longest_side``.

    Resizing first is what makes the metric robust: 4px shifts that would
    score badly at native resolution become sub-pixel after downscale.
    """
    if im.mode != "RGB":
        im = im.convert("RGB")
    w, h = im.size
    if max(w, h) > longest_side:
        if w >= h:
            new_w = longest_side
            new_h = max(1, int(round(h * (longest_side / w))))
        else:
            new_h = longest_side
            new_w = max(1, int(round(w * (longest_side / h))))
        im = im.resize((new_w, new_h), Image.LANCZOS)
    return im


def _scale_to_height(im, target_h: int):
    w, h = im.size
    if h == target_h:
        return im
    ratio = target_h / h
    return im.resize((max(1, int(round(w * ratio))), target_h), Image.LANCZOS)


def _compute_diff_box(diff_image) -> Optional[Tuple[int, int, int, int]]:
    """Bounding box of pixels that differ by >8 units in the diff image."""
    try:
        gray = diff_image.convert("L")
        mask = gray.point(lambda px: 255 if px > 8 else 0)
        bbox = mask.getbbox()
        return bbox
    except Exception:
        return None
