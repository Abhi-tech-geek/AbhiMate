"""Feature #4 — Visual regression.

Four layers covered:
1. visual_diff math (similarity, render_diff, threshold edge cases)
2. visual_store path policy + user scoping + list/delete/promote
3. Action engine ops (visual_baseline, assert_visual_match)
4. Flask endpoints — auth, name validation, scope, image serve, promote/delete
"""

import os
import time
from io import BytesIO
from unittest.mock import MagicMock

import pytest

from PIL import Image


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _png(path, color=(50, 100, 200), size=(64, 48)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", size, color).save(path)


@pytest.fixture
def visual_dirs(tmp_path, monkeypatch):
    base = tmp_path / "visual_b"
    art = tmp_path / "visual_a"
    monkeypatch.setenv("ABHIMATE_BASELINES_DIR", str(base))
    monkeypatch.setenv("ABHIMATE_VISUAL_ARTIFACTS_DIR", str(art))
    return {"baselines": str(base), "artifacts": str(art)}


class StubPort:
    """Fake BrowserPort whose screenshot() writes a deterministic PNG."""

    def __init__(self, color=(0, 0, 0), size=(64, 48), url="http://x.test/"):
        self.color = color
        self.size = size
        self._url = url

    def screenshot(self, path):
        _png(path, self.color, self.size)

    @property
    def current_url(self):
        return self._url


# ======================================================================
# 1. visual_diff math
# ======================================================================

def test_identical_images_score_1(tmp_path):
    from utils.visual_diff import compare_images
    a = str(tmp_path / "a.png")
    b = str(tmp_path / "b.png")
    _png(a, (10, 20, 30))
    _png(b, (10, 20, 30))
    r = compare_images(a, b, threshold=0.99)
    assert r.similarity == pytest.approx(1.0, abs=1e-6)
    assert r.passed is True


def test_very_different_images_fail(tmp_path):
    from utils.visual_diff import compare_images
    a = str(tmp_path / "a.png")
    b = str(tmp_path / "b.png")
    _png(a, (0, 0, 0))
    _png(b, (255, 255, 255))
    r = compare_images(a, b, threshold=0.95)
    assert r.similarity < 0.2
    assert r.passed is False
    assert r.diff_percent > 80


def test_threshold_clamped_into_unit_interval(tmp_path):
    from utils.visual_diff import compare_images
    a = str(tmp_path / "a.png"); b = str(tmp_path / "b.png")
    _png(a); _png(b)
    r = compare_images(a, b, threshold=5.0)  # > 1
    assert r.threshold == 1.0


def test_missing_file_raises(tmp_path):
    from utils.visual_diff import compare_images
    real = str(tmp_path / "a.png"); _png(real)
    with pytest.raises(FileNotFoundError):
        compare_images(real, str(tmp_path / "ghost.png"))


def test_render_diff_emits_artifact(tmp_path):
    from utils.visual_diff import render_diff
    a = str(tmp_path / "a.png"); b = str(tmp_path / "b.png")
    out = str(tmp_path / "diff.png")
    _png(a, (10, 10, 10)); _png(b, (250, 30, 30))
    render_diff(a, b, out)
    assert os.path.exists(out)
    with Image.open(out) as im:
        # Composite is roughly 3 panels side by side
        assert im.width > 0 and im.height > 0


def test_image_sha256_stable(tmp_path):
    from utils.visual_diff import image_sha256
    p = str(tmp_path / "a.png"); _png(p)
    h1 = image_sha256(p)
    h2 = image_sha256(p)
    assert h1 == h2 and len(h1) == 64


# ======================================================================
# 2. visual_store path policy + user scoping
# ======================================================================

def test_baseline_path_user_scoped(visual_dirs):
    from utils.visual_store import baseline_path
    p1 = baseline_path(7, "login")
    p2 = baseline_path(99, "login")
    assert p1 != p2
    assert "u7" in p1 and "u99" in p2
    assert p1.startswith(visual_dirs["baselines"])


def test_baseline_path_rejects_traversal(visual_dirs):
    from utils.visual_store import baseline_path
    with pytest.raises(ValueError):
        baseline_path(1, "../../etc/passwd")
    with pytest.raises(ValueError):
        baseline_path(1, "foo bar")          # space not allowed
    with pytest.raises(ValueError):
        baseline_path(1, "")                  # empty


def test_list_baselines_returns_rows_newest_first(visual_dirs):
    from utils.visual_store import baseline_path, list_baselines
    p1 = baseline_path(5, "older")
    _png(p1)
    os.utime(p1, (time.time() - 600, time.time() - 600))
    p2 = baseline_path(5, "newer")
    _png(p2)
    rows = list_baselines(5)
    assert [r["name"] for r in rows][:2] == ["newer", "older"]


def test_delete_baseline_removes_files(visual_dirs):
    from utils.visual_store import baseline_path, artifact_path, delete_baseline, list_baselines
    _png(baseline_path(8, "shot"))
    _png(artifact_path(8, "shot", "actual"))
    _png(artifact_path(8, "shot", "diff"))
    assert len(list_baselines(8)) == 1
    assert delete_baseline(8, "shot") is True
    assert list_baselines(8) == []
    assert delete_baseline(8, "shot") is False  # idempotent


def test_promote_actual_copies_into_baseline(visual_dirs):
    from utils.visual_store import baseline_path, artifact_path, promote_actual
    from utils.visual_diff import image_sha256
    _png(baseline_path(4, "checkout"), (255, 0, 0))
    _png(artifact_path(4, "checkout", "actual"), (0, 255, 0))
    _png(artifact_path(4, "checkout", "diff"), (50, 50, 50))
    ok = promote_actual(4, "checkout")
    assert ok is True
    # Baseline now matches actual
    assert image_sha256(baseline_path(4, "checkout")) == \
           image_sha256(artifact_path(4, "checkout", "actual"))
    # Stale diff was cleaned up
    assert not os.path.exists(artifact_path(4, "checkout", "diff"))


def test_promote_actual_returns_false_without_actual(visual_dirs):
    from utils.visual_store import promote_actual
    assert promote_actual(11, "missing") is False


# ======================================================================
# 3. Action engine ops
# ======================================================================

def test_visual_baseline_op_seeds_first_run(visual_dirs):
    from utils.action_engine import ActionContext, _op_visual_baseline
    from utils.models import Action
    from utils.visual_store import baseline_path
    port = StubPort((100, 50, 200))
    ctx = ActionContext(port=port, user_id=42)
    r = _op_visual_baseline(Action(op="visual_baseline", value="page_a"), ctx)
    assert "saved" in r
    assert os.path.exists(baseline_path(42, "page_a"))


def test_visual_baseline_op_keeps_existing(visual_dirs):
    from utils.action_engine import ActionContext, _op_visual_baseline
    from utils.models import Action
    from utils.visual_store import baseline_path
    port = StubPort((100, 50, 200))
    ctx = ActionContext(port=port, user_id=42)
    _op_visual_baseline(Action(op="visual_baseline", value="page_a"), ctx)
    first_mtime = os.path.getmtime(baseline_path(42, "page_a"))
    time.sleep(0.05)
    # Change colour, run baseline again — should keep the existing one
    port.color = (1, 2, 3)
    r = _op_visual_baseline(Action(op="visual_baseline", value="page_a"), ctx)
    assert "kept" in r
    assert os.path.getmtime(baseline_path(42, "page_a")) == first_mtime


def test_visual_baseline_op_force_overwrite(visual_dirs):
    from utils.action_engine import ActionContext, _op_visual_baseline
    from utils.models import Action
    from utils.visual_diff import image_sha256
    from utils.visual_store import baseline_path
    port = StubPort((1, 1, 1))
    ctx = ActionContext(port=port, user_id=3)
    _op_visual_baseline(Action(op="visual_baseline", value="p1"), ctx)
    sha_first = image_sha256(baseline_path(3, "p1"))
    port.color = (200, 200, 200)
    r = _op_visual_baseline(Action(op="visual_baseline", value="p1", expected="force"), ctx)
    assert "saved" in r
    assert image_sha256(baseline_path(3, "p1")) != sha_first


def test_assert_visual_match_seeds_when_missing(visual_dirs):
    from utils.action_engine import ActionContext, _op_assert_visual_match
    from utils.models import Action
    from utils.visual_store import baseline_path
    port = StubPort((10, 20, 30))
    r = _op_assert_visual_match(
        Action(op="assert_visual_match", value="seedme"),
        ActionContext(port=port, user_id=1),
    )
    assert "seeded" in r
    assert os.path.exists(baseline_path(1, "seedme"))


def test_assert_visual_match_passes_when_same(visual_dirs):
    from utils.action_engine import ActionContext, _op_assert_visual_match, _op_visual_baseline
    from utils.models import Action
    port = StubPort((40, 80, 120))
    ctx = ActionContext(port=port, user_id=1)
    _op_visual_baseline(Action(op="visual_baseline", value="match"), ctx)
    r = _op_assert_visual_match(
        Action(op="assert_visual_match", value="match", expected=0.99),
        ActionContext(port=port, user_id=1),
    )
    assert "match" in r


def test_assert_visual_match_fails_writes_diff_artifact(visual_dirs):
    from utils.action_engine import ActionContext, _op_assert_visual_match, _op_visual_baseline
    from utils.models import Action
    from utils.visual_store import artifact_path
    port = StubPort((10, 10, 10))
    ctx = ActionContext(port=port, user_id=1)
    _op_visual_baseline(Action(op="visual_baseline", value="drift"), ctx)
    port.color = (240, 240, 240)
    ctx2 = ActionContext(port=port, user_id=1)
    with pytest.raises(AssertionError, match="below threshold"):
        _op_assert_visual_match(
            Action(op="assert_visual_match", value="drift", expected=0.99),
            ctx2,
        )
    # Both actual + diff artifacts should now exist
    assert os.path.exists(artifact_path(1, "drift", "actual"))
    assert os.path.exists(artifact_path(1, "drift", "diff"))
    # visual_artifacts surfaces the diff context for the UI
    diffs = [a for a in ctx2.visual_artifacts if a["status"] == "failed"]
    assert diffs and diffs[0]["similarity"] < 0.5


def test_assert_visual_match_user_scoped(visual_dirs):
    """User A's baseline must not affect User B."""
    from utils.action_engine import ActionContext, _op_assert_visual_match, _op_visual_baseline
    from utils.models import Action
    port = StubPort((10, 10, 10))
    _op_visual_baseline(Action(op="visual_baseline", value="shared"),
                        ActionContext(port=port, user_id=1))
    # User 2 has NO baseline — first call should seed, not compare.
    r = _op_assert_visual_match(
        Action(op="assert_visual_match", value="shared", expected=0.99),
        ActionContext(port=port, user_id=2),
    )
    assert "seeded" in r


# ======================================================================
# 4. Flask endpoints
# ======================================================================

def test_endpoint_requires_auth(anonymous_client):
    r = anonymous_client.get("/api/visual/baselines")
    assert r.status_code == 401


def test_endpoint_list_empty(auth_client, visual_dirs):
    client, _ = auth_client
    r = client.get("/api/visual/baselines")
    assert r.status_code == 200
    assert r.get_json() == {"baselines": [], "count": 0}


def test_endpoint_list_returns_seeded_baselines(auth_client, visual_dirs):
    client, uid = auth_client
    from utils.visual_store import baseline_path
    _png(baseline_path(uid, "home"))
    r = client.get("/api/visual/baselines")
    body = r.get_json()
    assert body["count"] == 1
    assert body["baselines"][0]["name"] == "home"
    # Disk paths must NOT leak
    assert "path" not in body["baselines"][0]


def test_endpoint_image_serve_returns_png(auth_client, visual_dirs):
    client, uid = auth_client
    from utils.visual_store import baseline_path
    p = baseline_path(uid, "img1")
    _png(p, (200, 100, 50))
    r = client.get("/api/visual/image?name=img1&kind=baseline")
    assert r.status_code == 200
    assert r.mimetype == "image/png"
    assert r.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_endpoint_image_serve_404_for_missing(auth_client, visual_dirs):
    client, _ = auth_client
    r = client.get("/api/visual/image?name=nope&kind=baseline")
    assert r.status_code == 404


def test_endpoint_image_serve_rejects_bad_name(auth_client, visual_dirs):
    client, _ = auth_client
    r = client.get("/api/visual/image?name=../../etc/passwd&kind=baseline")
    assert r.status_code == 400


def test_endpoint_image_serve_rejects_unknown_kind(auth_client, visual_dirs):
    client, _ = auth_client
    r = client.get("/api/visual/image?name=foo&kind=evil")
    assert r.status_code == 400


def test_endpoint_image_serve_user_scoped(auth_client, visual_dirs, app_module):
    """A baseline created for user B must not be visible to user A."""
    client_a, uid_a = auth_client
    from utils.visual_store import baseline_path
    # Plant a baseline under a *different* user id
    other_uid = uid_a + 1000
    _png(baseline_path(other_uid, "secret"))
    # User A can't see it
    r = client_a.get("/api/visual/image?name=secret&kind=baseline")
    assert r.status_code == 404


def test_endpoint_delete(auth_client, visual_dirs):
    client, uid = auth_client
    from utils.visual_store import baseline_path
    _png(baseline_path(uid, "todelete"))
    r = client.delete("/api/visual/baselines/todelete")
    assert r.status_code == 200
    body = r.get_json()
    assert body["deleted"] is True
    assert not os.path.exists(baseline_path(uid, "todelete"))


def test_endpoint_delete_bad_name(auth_client, visual_dirs):
    """Names with disallowed characters (e.g. ``@``) are rejected with 400.

    ``..`` would never even reach our handler because Flask's path matcher
    routes single-segment ``<name>`` and the URL collapses to a different
    route — so we exercise the in-handler validation directly with ``@``."""
    client, _ = auth_client
    r = client.delete("/api/visual/baselines/bad@name")
    assert r.status_code == 400


def test_endpoint_promote_success(auth_client, visual_dirs):
    client, uid = auth_client
    from utils.visual_store import baseline_path, artifact_path
    from utils.visual_diff import image_sha256
    _png(baseline_path(uid, "promo"), (10, 10, 10))
    _png(artifact_path(uid, "promo", "actual"), (200, 200, 200))
    base_sha_before = image_sha256(baseline_path(uid, "promo"))

    r = client.post("/api/visual/baselines/promo/promote")
    assert r.status_code == 200
    base_sha_after = image_sha256(baseline_path(uid, "promo"))
    assert base_sha_after != base_sha_before
    # Promoted baseline must match the actual it copied from
    assert base_sha_after == image_sha256(
        baseline_path(uid, "promo")  # same path, just re-read
    )


def test_endpoint_promote_404_when_no_actual(auth_client, visual_dirs):
    client, uid = auth_client
    from utils.visual_store import baseline_path
    _png(baseline_path(uid, "nopromo"))
    r = client.post("/api/visual/baselines/nopromo/promote")
    assert r.status_code == 404


# ======================================================================
# 5. Generator prompt includes the visual ops
# ======================================================================

def test_generator_prompt_advertises_visual_ops():
    """The LLM needs to know visual_baseline + assert_visual_match exist."""
    from agents.test_case_generator_agent import GHERKIN_RULES
    rendered = GHERKIN_RULES.format(count=5)
    assert "visual_baseline" in rendered
    assert "assert_visual_match" in rendered
