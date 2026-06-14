"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str

Error handling convention: tools raise `ToolError` on any unrecoverable
failure. The agent loop wraps each tool call in try/except and writes the
exception message to session['error'] before returning early. An empty
successful result (e.g., search_listings returning []) is NOT an error.
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings


class ToolError(Exception):
    """Raised by a FitFindr tool when it cannot complete its work.

    The agent loop catches this, writes the message to session['error'],
    and returns early. A no-results outcome is a normal return value, not
    a ToolError — only raise for unrecoverable failures (IO errors, LLM
    failures, invalid input the tool can't handle).
    """


_STOPWORDS = {
    "a", "an", "the", "of", "in", "and", "or", "for", "with",
    "to", "is", "it", "this", "that", "on", "at", "by",
}

load_dotenv()


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match
        first), capped at the top 3. Returns an empty list if nothing
        matches — an empty result is NOT an error. The agent loop is
        responsible for deciding whether to retry with looser filters.

    Raises:
        ToolError: if the listings dataset cannot be loaded.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    try:
        listings = load_listings()
    except (FileNotFoundError, ValueError) as e:
        raise ToolError(f"Failed to load listings dataset: {e}") from e

    if max_price is not None:
        listings = [l for l in listings if l["price"] <= max_price]

    if size:
        listings = [l for l in listings if _size_matches(size, l["size"])]

    query_tokens = _tokenize(description)
    if not query_tokens:
        return []

    scored = []
    for listing in listings:
        haystack = " ".join([
            listing.get("title", ""),
            listing.get("description", ""),
            listing.get("category", ""),
            " ".join(listing.get("style_tags", [])),
        ])
        listing_tokens = _tokenize(haystack)
        score = len(query_tokens & listing_tokens)
        if score > 0:
            scored.append((score, listing))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [listing for _, listing in scored[:3]]


def _tokenize(text: str) -> set[str]:
    """Lowercase + extract word tokens, dropping common stopwords."""
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS}


def _size_matches(requested: str, listing_size: str) -> bool:
    """
    A listing matches the requested size if every token in `requested` appears
    in the listing's size tokens. Splits on `/` and whitespace, case-insensitive.
    Example: requested="M" matches listing_size="S/M" because {"m"} ⊆ {"s","m"}.
    """
    req = {t for t in re.split(r"[/\s]+", requested.lower()) if t}
    have = {t for t in re.split(r"[/\s]+", listing_size.lower()) if t}
    return req.issubset(have) if req else True


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions. If the wardrobe is empty,
        return general styling advice for the item (this is NOT an error —
        still return a string).

    Raises:
        ToolError: if the LLM call fails or returns an empty / unusable
                   response. The agent loop catches this and writes the
                   message to session['error'].

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.
        5. If the LLM call raises or returns nothing, wrap the original
           exception in `raise ToolError(...) from e` rather than returning
           a partial / empty string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    # Replace this with your implementation
    return ""


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.

    Raises:
        ToolError: if `outfit` is empty/whitespace-only, if `new_item` is
                   missing required fields, or if the LLM call fails. The
                   agent loop catches this and writes the message to
                   session['error'].

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string —
           raise ToolError rather than calling the LLM with bad input.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response string.
        4. If the LLM call raises or returns nothing, wrap with
           `raise ToolError(...) from e` instead of returning an empty /
           partial string.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # Replace this with your implementation
    return ""
