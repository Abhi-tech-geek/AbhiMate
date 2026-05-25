"""On-disk baseline + artifact storage for visual regression (Feature #4).

The action engine writes baselines and artifacts. This module owns the
**read** side — list, fetch, delete, promote — so endpoints stay thin
and the path policy lives in one place.

Layout:
    data/visual_baselines/u<user_id>/<name>.png
    data/visual_baselines/u<user_id>/<name>.json   (sidecar)
    data/visual_artifacts/u<user_id>/<name>__actual.png
    data/visual_artifacts/u<user_id>/<name>__diff.png

Both roots are overridable via env vars used by tests so they don't
write into a developer's real data folder.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from typing import List, Optional

VISUAL_BASELINES_ROOT = "data/visual_baselines"
VISUAL_ARTIFACTS_ROOT = "data/visual_artifacts"

# Same alphabet as auth_state_path — keeps names URL-safe + traversal-proof.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def baselines_root() -> str:
    return os.environ.get("ABHIMATE_BASELINES_DIR") or VISUAL_BASELINES_ROOT


def artifacts_root() -> str:
    return os.environ.get("ABHIMATE_VISUAL_ARTIFACTS_DIR") or VISUAL_ARTIFACTS_ROOT


def user_bucket(user_id: Optional[int]) -> str:
    return f"u{int(user_id)}" if user_id else "_shared"


def _sanitize(name: str) -> str:
    if not name:
        raise ValueError("visual name is required")
    if not _SAFE_NAME_RE.match(name):
        raise ValueError(
            f"invalid visual name '{name}': use letters, digits, '.', '_', '-' only"
        )
    return name


def _safe_join(root: str, *parts: str) -> str:
    """Join under ``root`` and refuse anything that escapes the sandbox."""
    base = os.path.abspath(root)
    candidate = os.path.abspath(os.path.join(base, *parts))
    if not (candidate == base or candidate.startswith(base + os.sep)):
        raise ValueError("visual path escapes the sandbox")
    return candidate


def baseline_path(user_id: Optional[int], name: str) -> str:
    return _safe_join(baselines_root(), user_bucket(user_id), _sanitize(name) + ".png")


def baseline_sidecar(user_id: Optional[int], name: str) -> str:
    return _safe_join(baselines_root(), user_bucket(user_id), _sanitize(name) + ".json")


def artifact_path(user_id: Optional[int], name: str, kind: str) -> str:
    """``kind`` is 'actual' or 'diff'. The artifact file is named
    ``<name>__actual.png`` / ``<name>__diff.png``."""
    if kind not in ("actual", "diff"):
        raise ValueError(f"unknown artifact kind '{kind}'")
    return _safe_join(
        artifacts_root(),
        user_bucket(user_id),
        f"{_sanitize(name)}__{kind}.png",
    )


def list_baselines(user_id: Optional[int]) -> List[dict]:
    """Return one row per baseline image for the user, newest first.

    Each row carries the metadata sidecar plus computed flags (has_actual,
    has_diff) so the UI can show a Promote / View-diff button conditionally.
    """
    bucket_dir = _safe_join(baselines_root(), user_bucket(user_id))
    if not os.path.isdir(bucket_dir):
        return []
    rows: List[dict] = []
    for fname in sorted(os.listdir(bucket_dir)):
        if not fname.endswith(".png"):
            continue
        name = fname[:-4]
        path = os.path.join(bucket_dir, fname)
        meta = {}
        sidecar = os.path.join(bucket_dir, name + ".json")
        if os.path.isfile(sidecar):
            try:
                with open(sidecar, "r", encoding="utf-8") as fh:
                    meta = json.load(fh) or {}
            except Exception:
                meta = {}
        rows.append({
            "name": name,
            "path": path,
            "bytes": os.path.getsize(path),
            "mtime": os.path.getmtime(path),
            "width": meta.get("width"),
            "height": meta.get("height"),
            "url": meta.get("url"),
            "created_at": meta.get("created_at"),
            "sha256": (meta.get("sha256") or "")[:16],
            "has_actual": os.path.isfile(_artifact_silent(user_id, name, "actual")),
            "has_diff": os.path.isfile(_artifact_silent(user_id, name, "diff")),
        })
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return rows


def _artifact_silent(user_id: Optional[int], name: str, kind: str) -> str:
    """artifact_path without raising on bad name — for listing flags only."""
    try:
        return artifact_path(user_id, name, kind)
    except Exception:
        return ""


def delete_baseline(user_id: Optional[int], name: str) -> bool:
    """Remove the baseline PNG, its sidecar, and any leftover artifacts.

    Returns True if at least one file was removed.
    """
    removed = False
    for path in (
        baseline_path(user_id, name),
        baseline_sidecar(user_id, name),
        _artifact_silent(user_id, name, "actual"),
        _artifact_silent(user_id, name, "diff"),
    ):
        if path and os.path.isfile(path):
            try:
                os.remove(path)
                removed = True
            except OSError:
                pass
    return removed


def promote_actual(user_id: Optional[int], name: str) -> bool:
    """Replace the baseline with the most recent actual screenshot.

    Used when a visual diff failed because the UI intentionally changed —
    one click in the UI accepts the new look as the baseline.
    Returns True on success, False if there's no actual to promote.
    """
    actual = _artifact_silent(user_id, name, "actual")
    if not (actual and os.path.isfile(actual)):
        return False
    bp = baseline_path(user_id, name)
    os.makedirs(os.path.dirname(bp), exist_ok=True)
    shutil.copy2(actual, bp)
    # Refresh sidecar
    try:
        from utils.visual_diff import image_sha256, image_size
        import time as _time
        w, h = image_size(bp)
        with open(baseline_sidecar(user_id, name), "w", encoding="utf-8") as fh:
            json.dump({
                "name": name, "kind": "baseline",
                "user_id": user_id,
                "width": w, "height": h,
                "sha256": image_sha256(bp),
                "created_at": _time.time(),
                "promoted_from": "actual",
            }, fh, indent=2)
    except Exception:
        pass
    # Diff is stale now; remove it.
    diff = _artifact_silent(user_id, name, "diff")
    if diff and os.path.isfile(diff):
        try:
            os.remove(diff)
        except OSError:
            pass
    return True
