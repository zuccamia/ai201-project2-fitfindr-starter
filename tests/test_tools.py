"""
Tests for the three FitFindr tools.

Each tool has at least one test covering its documented failure mode
(see planning.md → Error Handling). Tests for tools that are still stubs
are marked with pytest.mark.skip — remove the skip once they're implemented.

Run from the project root:
    pytest tests/
"""

import pytest

from tools import (
    ToolError,
    create_fit_card,
    search_listings,
    suggest_outfit,
    update_style_profile,
)
from utils.data_loader import get_empty_wardrobe, get_example_wardrobe


# ── search_listings ───────────────────────────────────────────────────────────

class TestSearchListings:
    def test_returns_relevant_results(self):
        results = search_listings("vintage graphic tee", size="M", max_price=30.0)
        assert len(results) > 0
        top = results[0]
        text = (top["title"] + " " + top["description"] + " " + " ".join(top["style_tags"])).lower()
        assert any(kw in text for kw in ("vintage", "graphic", "tee"))

    def test_filters_by_max_price(self):
        results = search_listings("shirt", max_price=20.0)
        assert results, "expected some results under $20"
        assert all(r["price"] <= 20.0 for r in results)

    def test_size_filter_matches_compound_sizes(self):
        # "M" should match listings sized "S/M" or "M/L", per the spec example.
        results = search_listings("tee", size="M")
        assert results, "expected tee results in size M / S/M / M/L"
        for r in results:
            assert _size_tokens(r["size"]) >= {"m"} or "m" in _size_tokens(r["size"])

    def test_size_filter_is_case_insensitive(self):
        upper = search_listings("tee", size="M")
        lower = search_listings("tee", size="m")
        assert [r["id"] for r in upper] == [r["id"] for r in lower]

    def test_returns_at_most_three_results(self):
        # "vintage" is broad — many listings carry that tag.
        results = search_listings("vintage")
        assert len(results) <= 3

    def test_sorted_by_relevance_descending(self):
        # A multi-keyword query lets us check ordering: items matching more
        # query tokens should rank above items matching fewer.
        results = search_listings("vintage denim jeans")
        if len(results) >= 2:
            top_text = (results[0]["title"] + " " + " ".join(results[0]["style_tags"])).lower()
            last_text = (results[-1]["title"] + " " + " ".join(results[-1]["style_tags"])).lower()
            top_hits = sum(kw in top_text for kw in ("vintage", "denim", "jeans"))
            last_hits = sum(kw in last_text for kw in ("vintage", "denim", "jeans"))
            assert top_hits >= last_hits

    # ── FAILURE MODE: no listings match the query ─────────────────────────────
    def test_no_match_returns_empty_list(self):
        """Per planning.md error handling: agent should see [] (not an exception)
        so it can decide whether to retry with loosened constraints."""
        results = search_listings("xyzzy spaceship laser unicorn")
        assert results == []

    def test_impossible_price_returns_empty_list(self):
        results = search_listings("tee", max_price=0.01)
        assert results == []

    def test_raises_tool_error_when_dataset_missing(self, monkeypatch):
        """If the listings dataset can't be loaded, the tool raises ToolError
        so the agent loop can catch it and write to session['error']."""
        def _broken_loader():
            raise FileNotFoundError("listings.json missing")

        monkeypatch.setattr("tools.load_listings", _broken_loader)
        with pytest.raises(ToolError, match="Failed to load listings"):
            search_listings("vintage tee")


def _size_tokens(s: str) -> set[str]:
    import re
    return {t for t in re.split(r"[/\s]+", s.lower()) if t}


# ── suggest_outfit ────────────────────────────────────────────────────────────

class TestSuggestOutfit:
    """The Groq client is monkeypatched in every test so nothing hits the network."""

    NEW_ITEM = {
        "id": "lst_002",
        "title": "Y2K Baby Tee — Butterfly Print",
        "category": "tops",
        "style_tags": ["y2k", "vintage", "graphic tee"],
        "colors": ["white", "pink"],
        "description": "Fitted crop length, soft cotton.",
    }

    def test_populated_wardrobe_prompt_names_wardrobe_items(self, monkeypatch):
        """The populated-wardrobe branch must put specific wardrobe item names
        into the LLM prompt, not just the new item — that's how the LLM can
        suggest 'pair with your X' instead of generic advice."""
        from utils.data_loader import get_example_wardrobe

        captured = {}
        monkeypatch.setattr("tools._get_groq_client", _make_fake_client(captured, reply="ok"))

        suggest_outfit(self.NEW_ITEM, get_example_wardrobe())

        user_prompt = captured["messages"][-1]["content"]
        # At least three different wardrobe item names should appear in the prompt.
        wardrobe_names = [it["name"] for it in get_example_wardrobe()["items"]]
        hits = sum(1 for name in wardrobe_names if name in user_prompt)
        assert hits >= 3, f"prompt mentioned only {hits} wardrobe items: {wardrobe_names}"

    # ── FAILURE MODE: wardrobe is empty (NOT a ToolError) ────────────────────
    def test_empty_wardrobe_returns_general_advice(self, monkeypatch):
        """Per planning.md: empty wardrobe is NOT an error — the tool still
        returns a string with general styling advice."""
        captured = {}
        monkeypatch.setattr(
            "tools._get_groq_client",
            _make_fake_client(captured, reply="Try high-waisted jeans and chunky boots."),
        )

        result = suggest_outfit(self.NEW_ITEM, get_empty_wardrobe())

        assert isinstance(result, str)
        assert result.strip(), "expected non-empty general styling advice"
        # The empty-wardrobe prompt should NOT reference wardrobe items by name
        # (there are none) — it should ask for types of pieces.
        user_prompt = captured["messages"][-1]["content"]
        assert "wardrobe" in user_prompt.lower()

    # ── FAILURE MODE: LLM call fails (raises ToolError) ──────────────────────
    def test_llm_failure_raises_tool_error(self, monkeypatch):
        """Per planning.md: on LLM failure, raise ToolError so the agent loop
        can catch it and write the message to session['error']."""

        class _BrokenClient:
            class chat:
                class completions:
                    @staticmethod
                    def create(**_):
                        raise RuntimeError("API down")

        monkeypatch.setattr("tools._get_groq_client", lambda: _BrokenClient())

        with pytest.raises(ToolError, match="suggest_outfit LLM call failed"):
            suggest_outfit(self.NEW_ITEM, get_empty_wardrobe())

    def test_empty_llm_response_raises_tool_error(self, monkeypatch):
        """If the LLM returns an empty/whitespace string, raise rather than
        propagate a useless suggestion downstream."""
        captured = {}
        monkeypatch.setattr("tools._get_groq_client", _make_fake_client(captured, reply="   "))

        with pytest.raises(ToolError, match="empty response"):
            suggest_outfit(self.NEW_ITEM, get_empty_wardrobe())


def _make_fake_client(captured: dict, reply: str):
    """Return a factory function that builds a stand-in for the Groq client.
    The returned client records the messages it receives in `captured` and
    replies with `reply`."""
    class _Msg:
        def __init__(self, content): self.content = content
    class _Choice:
        def __init__(self, content): self.message = _Msg(content)
    class _Resp:
        def __init__(self, content): self.choices = [_Choice(content)]
    class _Completions:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            return _Resp(reply)
    class _Chat:
        completions = _Completions()
    class _Client:
        chat = _Chat()
    return lambda: _Client()


# ── create_fit_card ───────────────────────────────────────────────────────────

class TestCreateFitCard:
    """The Groq client is monkeypatched in every test so nothing hits the network."""

    NEW_ITEM = {
        "id": "lst_002",
        "title": "Y2K Baby Tee — Butterfly Print",
        "price": 18.0,
        "platform": "depop",
    }
    OUTFIT = (
        "Pair with your Baggy straight-leg jeans and Chunky white sneakers "
        "for a casual streetwear look."
    )

    def test_prompt_includes_item_name_price_and_platform(self, monkeypatch):
        """The LLM needs all three so the caption can mention them naturally
        (once each, per the spec)."""
        captured = {}
        monkeypatch.setattr("tools._get_groq_client", _make_fake_client(captured, reply="ok"))

        create_fit_card(self.OUTFIT, self.NEW_ITEM)

        user_prompt = captured["messages"][-1]["content"]
        assert "Y2K Baby Tee" in user_prompt
        assert "18.00" in user_prompt
        assert "depop" in user_prompt

    def test_uses_high_temperature_for_caption_variety(self, monkeypatch):
        """Captions should sound different each invocation — temperature must
        be elevated above the suggest_outfit default."""
        captured = {}
        monkeypatch.setattr("tools._get_groq_client", _make_fake_client(captured, reply="ok"))

        create_fit_card(self.OUTFIT, self.NEW_ITEM)

        assert captured.get("temperature", 0) >= 0.8

    # ── FAILURE MODE: outfit is empty/whitespace (graceful — NOT a raise) ────
    # The fit card is non-critical, so empty outfit returns a placeholder
    # string instead of failing the whole interaction. The agent still
    # stores it in session['fit_card'] so the user sees it in the UI.
    @pytest.mark.parametrize("bad_outfit", ["", "   ", "\n\t"])
    def test_empty_outfit_returns_placeholder_string(self, bad_outfit):
        result = create_fit_card(bad_outfit, self.NEW_ITEM)
        assert isinstance(result, str)
        assert result.strip(), "expected a non-empty placeholder string"
        assert "outfit" in result.lower() or "empty" in result.lower(), \
            f"placeholder should describe what went wrong, got: {result!r}"

    # ── FAILURE MODE: required new_item field missing (raises) ───────────────
    @pytest.mark.parametrize("missing", ["title", "price", "platform"])
    def test_missing_required_field_raises_tool_error(self, missing):
        item = dict(self.NEW_ITEM)
        del item[missing]
        with pytest.raises(ToolError, match=f"missing required field.*{missing}"):
            create_fit_card(self.OUTFIT, item)

    # ── FAILURE MODE: LLM call fails (raises ToolError) ──────────────────────
    def test_llm_failure_raises_tool_error(self, monkeypatch):
        class _BrokenClient:
            class chat:
                class completions:
                    @staticmethod
                    def create(**_):
                        raise RuntimeError("API down")

        monkeypatch.setattr("tools._get_groq_client", lambda: _BrokenClient())

        with pytest.raises(ToolError, match="create_fit_card LLM call failed"):
            create_fit_card(self.OUTFIT, self.NEW_ITEM)

    def test_empty_llm_response_raises_tool_error(self, monkeypatch):
        captured = {}
        monkeypatch.setattr("tools._get_groq_client", _make_fake_client(captured, reply="   "))

        with pytest.raises(ToolError, match="empty response"):
            create_fit_card(self.OUTFIT, self.NEW_ITEM)


# ── update_style_profile ──────────────────────────────────────────────────────

class TestUpdateStyleProfile:
    NEW_ITEM = {
        "id": "lst_033",
        "title": "Vintage Band Tee — Faded Grey",
        "category": "tops",
        "style_tags": ["vintage", "grunge", "band tee"],
        "size": "L",
        "condition": "fair",
        "price": 19.00,
        "colors": ["grey", "charcoal"],
        "brand": None,
        "platform": "depop",
    }

    def test_appends_item_to_empty_wardrobe(self):
        wardrobe = get_empty_wardrobe()
        updated = update_style_profile(self.NEW_ITEM, wardrobe)
        assert len(updated["items"]) == 1
        item = updated["items"][0]
        assert item["id"] == "w_001"
        assert item["name"] == "Vintage Band Tee — Faded Grey"
        assert item["category"] == "tops"
        assert item["colors"] == ["grey", "charcoal"]
        assert item["style_tags"] == ["vintage", "grunge", "band tee"]
        # notes synthesized from size/condition/platform/price
        assert "Size: L" in item["notes"]
        assert "depop" in item["notes"]
        assert "$19.00" in item["notes"]

    def test_preserves_existing_items_and_picks_next_id(self):
        wardrobe = get_example_wardrobe()
        starting_count = len(wardrobe["items"])
        existing_ids = [it["id"] for it in wardrobe["items"]]

        updated = update_style_profile(self.NEW_ITEM, wardrobe)

        assert len(updated["items"]) == starting_count + 1
        # All previously-present ids are still there
        for old_id in existing_ids:
            assert any(it["id"] == old_id for it in updated["items"])
        # The new id doesn't collide
        new_id = updated["items"][-1]["id"]
        assert new_id not in existing_ids
        # And it's one above the highest existing w_NNN
        max_existing = max(int(i.split("_")[1]) for i in existing_ids if i.startswith("w_"))
        assert new_id == f"w_{max_existing + 1:03d}"

    def test_does_not_mutate_input_wardrobe(self):
        """Pure function — caller's wardrobe must be untouched so Gradio's
        BrowserState can compare old vs new values cleanly."""
        wardrobe = get_example_wardrobe()
        before_len = len(wardrobe["items"])
        before_first_id = wardrobe["items"][0]["id"]

        update_style_profile(self.NEW_ITEM, wardrobe)

        assert len(wardrobe["items"]) == before_len
        assert wardrobe["items"][0]["id"] == before_first_id

    def test_handles_missing_optional_fields(self):
        """Listings sometimes have brand=None or no description — only
        `title` is required; everything else falls back to sensible defaults."""
        skinny_item = {"title": "Mystery Jacket", "category": "outerwear"}
        updated = update_style_profile(skinny_item, get_empty_wardrobe())
        item = updated["items"][0]
        assert item["name"] == "Mystery Jacket"
        assert item["category"] == "outerwear"
        assert item["colors"] == []
        assert item["style_tags"] == []
        assert item["notes"] is None  # nothing to synthesize from

    # ── FAILURE MODE: new_item missing required `title` (raises) ─────────────
    def test_missing_title_raises_tool_error(self):
        with pytest.raises(ToolError, match="missing required field 'title'"):
            update_style_profile({"category": "tops"}, get_empty_wardrobe())
