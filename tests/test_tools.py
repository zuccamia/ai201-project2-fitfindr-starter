"""
Tests for the three FitFindr tools.

Each tool has at least one test covering its documented failure mode
(see planning.md → Error Handling). Tests for tools that are still stubs
are marked with pytest.mark.skip — remove the skip once they're implemented.

Run from the project root:
    pytest tests/
"""

import pytest

from tools import ToolError, create_fit_card, search_listings, suggest_outfit
from utils.data_loader import get_empty_wardrobe


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

    # ── FAILURE MODE: outfit is empty/whitespace (raises) ────────────────────
    @pytest.mark.parametrize("bad_outfit", ["", "   ", "\n\t"])
    def test_empty_outfit_raises_tool_error(self, bad_outfit):
        with pytest.raises(ToolError, match="non-empty outfit"):
            create_fit_card(bad_outfit, self.NEW_ITEM)

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
