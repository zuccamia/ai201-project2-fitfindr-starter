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

import logging
import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

logger = logging.getLogger(__name__)


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
    logger.info(
        "search_listings: description=%r size=%r max_price=%r",
        description, size, max_price,
    )
    try:
        listings = load_listings()
    except (FileNotFoundError, ValueError) as e:
        logger.error("search_listings: dataset load failed: %s", e)
        raise ToolError(f"Failed to load listings dataset: {e}") from e

    total = len(listings)

    if max_price is not None:
        listings = [l for l in listings if l["price"] <= max_price]
    if size:
        listings = [l for l in listings if _size_matches(size, l["size"])]
    logger.debug(
        "search_listings: %d/%d listings after price+size filters",
        len(listings), total,
    )

    query_tokens = _tokenize(description)
    if not query_tokens:
        logger.warning("search_listings: description tokenized to empty set; returning []")
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
    results = [listing for _, listing in scored[:3]]
    logger.info(
        "search_listings: returning %d result(s)%s",
        len(results),
        " (top score=%d)" % scored[0][0] if scored else "",
    )
    if logger.isEnabledFor(logging.DEBUG):
        for score, listing in scored[:3]:
            logger.debug("  · score=%d id=%s title=%r", score, listing["id"], listing["title"])
    return results


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
    items = wardrobe.get("items", []) if isinstance(wardrobe, dict) else []
    item_summary = _format_new_item(new_item)
    logger.info(
        "suggest_outfit: item=%r wardrobe_items=%d",
        new_item.get("title", "?"), len(items),
    )

    if items:
        wardrobe_summary = _format_wardrobe_items(items)
        user_prompt = (
            f"A user is considering thrifting this item:\n{item_summary}\n\n"
            f"Their existing wardrobe:\n{wardrobe_summary}\n\n"
            "Suggest 1–2 complete outfit combinations using the thrifted item "
            "paired with SPECIFIC named pieces from their wardrobe above. "
            "Name the wardrobe pieces explicitly (e.g., \"pair with your "
            "Baggy straight-leg jeans and Chunky white sneakers\"). "
            "Add one short sentence describing the vibe. "
            "Keep the whole reply under 120 words. No preamble, no bullet markers."
        )
    else:
        user_prompt = (
            f"A user is considering thrifting this item:\n{item_summary}\n\n"
            "They haven't shared their existing wardrobe. Suggest one complete "
            "outfit by describing the TYPES of pieces that would pair well "
            "(e.g., \"high-waisted dark-wash jeans\", \"chunky black boots\"). "
            "Add one short sentence describing the vibe. "
            "Keep the whole reply under 120 words. No preamble, no bullet markers."
        )

    logger.debug("suggest_outfit: prompt %d chars", len(user_prompt))
    try:
        client = _get_groq_client()
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a thoughtful thrift styling assistant. "
                        "Give specific, actionable outfit suggestions in a "
                        "casual, confident voice."
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
        )
        suggestion = resp.choices[0].message.content
    except Exception as e:
        logger.error("suggest_outfit: LLM call failed: %s", e)
        raise ToolError(f"suggest_outfit LLM call failed: {e}") from e

    if not suggestion or not suggestion.strip():
        logger.error("suggest_outfit: LLM returned empty response")
        raise ToolError("suggest_outfit LLM returned an empty response")

    suggestion = suggestion.strip()
    logger.info("suggest_outfit: returning %d chars", len(suggestion))
    return suggestion


def _format_new_item(item: dict) -> str:
    """Render a listing dict as a compact bullet block for the LLM prompt."""
    if not isinstance(item, dict) or not item:
        return "(no item details provided)"
    parts = [f"- {item.get('title', 'Untitled item')}"]
    if item.get("category"):
        parts.append(f"  category: {item['category']}")
    if item.get("colors"):
        parts.append(f"  colors: {', '.join(item['colors'])}")
    if item.get("style_tags"):
        parts.append(f"  style tags: {', '.join(item['style_tags'])}")
    if item.get("description"):
        parts.append(f"  details: {item['description']}")
    return "\n".join(parts)


def _format_wardrobe_items(items: list[dict]) -> str:
    """Render the wardrobe item list so each piece is named explicitly in the prompt."""
    lines = []
    for it in items:
        name = it.get("name", "(unnamed item)")
        cat = it.get("category", "?")
        bits = [f"- {name} ({cat})"]
        if it.get("colors"):
            bits.append(f"colors: {', '.join(it['colors'])}")
        if it.get("style_tags"):
            bits.append(f"style: {', '.join(it['style_tags'])}")
        if it.get("notes"):
            bits.append(f"notes: {it['notes']}")
        lines.append("; ".join(bits))
    return "\n".join(lines)


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
    if not outfit or not outfit.strip():
        logger.error("create_fit_card: outfit is empty/whitespace")
        raise ToolError("create_fit_card requires a non-empty outfit string")

    title = new_item.get("title")
    price = new_item.get("price")
    platform = new_item.get("platform")

    missing = [k for k, v in [("title", title), ("price", price), ("platform", platform)] if not v]
    if missing:
        logger.error("create_fit_card: new_item missing field(s): %s", missing)
        raise ToolError(
            f"create_fit_card new_item missing required field(s): {', '.join(missing)}"
        )

    logger.info("create_fit_card: item=%r outfit=%d chars", title, len(outfit))

    user_prompt = (
        "Write a casual 2–4 sentence Instagram/TikTok caption for a thrifted find.\n\n"
        f"Item: {title}\n"
        f"Price: ${price:.2f}\n"
        f"Platform: {platform}\n"
        f"Outfit notes: {outfit.strip()}\n\n"
        "Voice rules:\n"
        "- Sound like a real OOTD post, not a product description.\n"
        "- Mention the item name, price, and platform naturally (once each).\n"
        "- Capture the outfit's specific vibe — don't be generic.\n"
        "- Lowercase first-person is fine. Emoji optional, at most one.\n"
        "- No hashtags, no preamble — just the caption."
    )

    try:
        client = _get_groq_client()
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write short, casual, authentic-sounding OOTD "
                        "captions for thrifted finds."
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.9,
        )
        caption = resp.choices[0].message.content
    except Exception as e:
        logger.error("create_fit_card: LLM call failed: %s", e)
        raise ToolError(f"create_fit_card LLM call failed: {e}") from e

    if not caption or not caption.strip():
        logger.error("create_fit_card: LLM returned empty response")
        raise ToolError("create_fit_card LLM returned an empty response")

    caption = caption.strip()
    logger.info("create_fit_card: returning %d chars", len(caption))
    return caption
