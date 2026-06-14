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
    # ── FAILURE MODE: wardrobe is empty (NOT a ToolError) ────────────────────
    @pytest.mark.skip(reason="suggest_outfit is still a stub")
    def test_empty_wardrobe_returns_general_advice(self):
        """Per planning.md: if wardrobe['items'] is empty, fall back to general
        styling advice rather than raising. Empty wardrobe is NOT an error."""
        new_item = {
            "id": "lst_002",
            "title": "Y2K Baby Tee — Butterfly Print",
            "category": "tops",
            "style_tags": ["y2k", "vintage", "graphic tee"],
            "colors": ["white", "pink"],
            "price": 18.0,
        }
        result = suggest_outfit(new_item, get_empty_wardrobe())
        assert isinstance(result, str)
        assert result.strip(), "expected non-empty general styling advice"

    # ── FAILURE MODE: LLM call fails (raises ToolError) ──────────────────────
    @pytest.mark.skip(reason="suggest_outfit is still a stub")
    def test_llm_failure_raises_tool_error(self, monkeypatch):
        """Per planning.md: on LLM failure, raise ToolError so the agent loop
        can catch it and write the message to session['error']."""
        # Once implemented, monkeypatch the LLM client to raise, then:
        #   with pytest.raises(ToolError):
        #       suggest_outfit({...}, get_empty_wardrobe())
        ...


# ── create_fit_card ───────────────────────────────────────────────────────────

class TestCreateFitCard:
    # ── FAILURE MODE: outfit input is missing or incomplete (raises) ─────────
    @pytest.mark.skip(reason="create_fit_card is still a stub")
    def test_empty_outfit_raises_tool_error(self):
        """Per planning.md: empty outfit raises ToolError so the agent loop
        can catch it and write the message to session['error']."""
        new_item = {
            "id": "lst_002",
            "title": "Y2K Baby Tee",
            "price": 18.0,
            "platform": "depop",
        }
        with pytest.raises(ToolError):
            create_fit_card("", new_item)
