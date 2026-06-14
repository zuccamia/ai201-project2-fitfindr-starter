"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import json
import logging

from tools import (
    ToolError,
    _get_groq_client,
    create_fit_card,
    search_listings,
    suggest_outfit,
)

logger = logging.getLogger(__name__)


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    session = _new_session(query, wardrobe)
    logger.info("=== run_agent start: query=%r wardrobe_items=%d ===",
                query, len(wardrobe.get("items", []) if isinstance(wardrobe, dict) else []))

    # Step 2: parse the natural-language query into structured search params.
    logger.info("Step 2: parse query")
    try:
        session["parsed"] = _parse_query(query)
    except ToolError as e:
        session["error"] = f"Failed to parse user's request: {e}"
        logger.error("Step 2 failed: %s", session["error"])
        return session
    logger.info("Step 2: parsed=%s", session["parsed"])

    parsed = session["parsed"]

    # Step 3: search for matching listings. Retry once without the size
    # filter if the first call returns empty (per planning.md).
    logger.info("Step 3: search_listings")
    try:
        results = search_listings(
            description=parsed["description"],
            size=parsed.get("size"),
            max_price=parsed.get("max_price"),
        )
        if not results and parsed.get("size"):
            logger.warning("Step 3: 0 results — retrying without size filter")
            results = search_listings(
                description=parsed["description"],
                size=None,
                max_price=parsed.get("max_price"),
            )
    except ToolError as e:
        session["error"] = str(e)
        logger.error("Step 3 failed: %s", e)
        return session

    session["search_results"] = results

    if not results:
        constraints = [f"'{parsed['description']}'"]
        if parsed.get("size"):
            constraints.append(f"size {parsed['size']}")
        if parsed.get("max_price"):
            constraints.append(f"under ${parsed['max_price']:.0f}")
        session["error"] = (
            f"No listings found matching {', '.join(constraints)}. "
            "Try a different query or remove some constraints."
        )
        logger.error("Step 3 failed: %s", session["error"])
        return session

    # Step 4: pick the top result.
    session["selected_item"] = results[0]
    logger.info("Step 4: selected_item id=%s title=%r",
                results[0]["id"], results[0]["title"])

    # Step 5: ask the LLM for an outfit using the new item + wardrobe.
    logger.info("Step 5: suggest_outfit")
    try:
        session["outfit_suggestion"] = suggest_outfit(session["selected_item"], wardrobe)
    except ToolError as e:
        session["error"] = str(e)
        logger.error("Step 5 failed: %s", e)
        return session

    # Step 6: turn the suggestion into a shareable caption.
    logger.info("Step 6: create_fit_card")
    try:
        session["fit_card"] = create_fit_card(
            session["outfit_suggestion"],
            session["selected_item"],
        )
    except ToolError as e:
        session["error"] = str(e)
        logger.error("Step 6 failed: %s", e)
        return session

    logger.info("=== run_agent complete (success) ===")
    return session


# ── step 2 helper: query parsing ──────────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """LLM-extract {description, size, max_price} from a natural-language query.

    Returns a dict with `description` (non-empty str), `size` (str or None),
    and `max_price` (float or None). Raises ToolError if the LLM call fails
    or returns malformed / empty output.
    """
    user_prompt = (
        "Extract structured search fields from this thrift-shopping request:\n\n"
        f'"{query}"\n\n'
        "Return ONLY a JSON object with these keys:\n"
        '  - "description" (string, non-empty): brief item description to search\n'
        '  - "size" (string or null): size if specified, else null\n'
        '  - "max_price" (number or null): USD price ceiling if specified, else null\n\n'
        'Example: {"description": "vintage graphic tee", "size": "M", "max_price": 30}\n'
        "Output JSON only — no preamble, no markdown fences."
    )

    try:
        client = _get_groq_client()
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You extract structured search parameters from "
                        "natural-language thrift requests. Output only JSON."
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content
    except Exception as e:
        logger.error("parse_query: LLM call failed: %s", e)
        raise ToolError(f"parse_query LLM call failed: {e}") from e

    if not raw or not raw.strip():
        logger.error("parse_query: LLM returned empty response")
        raise ToolError("parse_query LLM returned an empty response")

    logger.debug("parse_query: raw LLM output=%r", raw)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("parse_query: non-JSON output: %r", raw)
        raise ToolError(f"parse_query LLM returned non-JSON output: {raw!r}") from e

    if not isinstance(parsed, dict) or not parsed.get("description"):
        logger.error("parse_query: malformed result: %r", parsed)
        raise ToolError(f"parse_query LLM returned malformed result: {parsed!r}")

    return {
        "description": str(parsed["description"]),
        "size": parsed.get("size") or None,
        "max_price": parsed.get("max_price"),
    }


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
