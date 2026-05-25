"""Quick checks on ModelSelectorAgent — guards UI dropdown wiring."""

from agents.model_selector_agent import ModelSelectorAgent


def test_default_is_accurate():
    sel = ModelSelectorAgent()
    assert sel.get_model() == sel.models["accurate"]


def test_fast_returns_8b():
    sel = ModelSelectorAgent()
    assert "8b" in sel.get_model("fast")


def test_unknown_falls_back_to_default():
    sel = ModelSelectorAgent()
    assert sel.get_model("nonsense") == sel.models["accurate"]


def test_models_are_current_groq_ids():
    sel = ModelSelectorAgent()
    # Sanity: no decommissioned ``llama3-*-8192`` IDs leaked back in.
    for mid in sel.models.values():
        assert "8192" not in mid, f"Decommissioned model ID surfaced: {mid}"
