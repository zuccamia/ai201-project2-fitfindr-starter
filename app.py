"""
app.py

Gradio interface for FitFindr. The layout and wiring are already set up —
your job is to fill in handle_query() so it calls run_agent() and maps
the session results to the three output panels.

Run with:
    python app.py

Then open the localhost URL shown in your terminal (usually http://localhost:7860,
but check your terminal — the port may differ).
"""

import logging
import os

import gradio as gr

from agent import run_agent
from tools import ToolError, update_style_profile
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    """Configure logging once when running app.py directly.

    Override the level by exporting FITFINDR_LOG_LEVEL=DEBUG (or WARNING,
    ERROR, etc.) before launching the app.
    """
    level = os.environ.get("FITFINDR_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ── query handler ─────────────────────────────────────────────────────────────

def handle_query(
    user_query: str,
    wardrobe_choice: str,
    my_wardrobe: dict,
) -> tuple[str, str, str, dict | None, str]:
    """
    Called by Gradio when the user submits a query.

    Args:
        user_query:      The text the user typed into the search box.
        wardrobe_choice: "My wardrobe" (uses my_wardrobe from BrowserState)
                         or "Example wardrobe" (uses the read-only fixture).
        my_wardrobe:     The user's persisted wardrobe dict (from
                         gr.BrowserState). May be empty for a new user.

    Returns:
        (listing_text, outfit_text, fit_card_text, selected_item, wardrobe_count_md)
        — first three are the output panels, selected_item is stashed in
        gr.State so the keep button can read it, and wardrobe_count_md
        refreshes the count display (in case the radio choice changed).
    """
    logger.info("handle_query: query=%r wardrobe_choice=%r", user_query, wardrobe_choice)
    count_md = _wardrobe_count_md(my_wardrobe)

    if not user_query or not user_query.strip():
        return "Please enter a search query to get started.", "", "", None, count_md

    wardrobe = (
        get_example_wardrobe() if wardrobe_choice == "Example wardrobe" else my_wardrobe
    )

    session = run_agent(query=user_query.strip(), wardrobe=wardrobe)

    if session["error"]:
        logger.info("handle_query: returning error to UI")
        return f"⚠️ {session['error']}", "", "", None, count_md

    logger.info("handle_query: returning full result to UI")
    return (
        _format_listing(session["selected_item"]),
        session["outfit_suggestion"] or "",
        session["fit_card"] or "",
        session["selected_item"],
        count_md,
    )


def handle_keep(my_wardrobe: dict, selected_item: dict | None) -> tuple[dict, str, str]:
    """
    Called when the user clicks "Keep this item". Adds the most recently
    surfaced listing to the user's saved wardrobe via update_style_profile.

    Returns:
        (updated_wardrobe, status_message, wardrobe_count_md)
        — updated_wardrobe gets persisted by gr.BrowserState.
    """
    if not selected_item:
        logger.info("handle_keep: no selected_item — ignoring click")
        return my_wardrobe, "Run a search first, then keep what you like.", _wardrobe_count_md(my_wardrobe)

    try:
        updated = update_style_profile(selected_item, my_wardrobe)
    except ToolError as e:
        logger.error("handle_keep: %s", e)
        return my_wardrobe, f"⚠️ {e}", _wardrobe_count_md(my_wardrobe)

    logger.info("handle_keep: added %r to wardrobe", selected_item.get("title"))
    return (
        updated,
        f"✓ Added '{selected_item['title']}' to your wardrobe.",
        _wardrobe_count_md(updated),
    )


def _wardrobe_count_md(wardrobe: dict) -> str:
    n = len(wardrobe.get("items", [])) if isinstance(wardrobe, dict) else 0
    return f"**My wardrobe:** {n} item(s) saved"


def _format_listing(item: dict) -> str:
    """Render a listing dict as a readable block for the listing output panel."""
    lines = [item["title"]]
    lines.append(f"${item['price']:.2f} on {item['platform']} · {item['condition']} condition")
    lines.append(f"Size: {item['size']}  ·  Category: {item['category']}")
    if item.get("brand"):
        lines.append(f"Brand: {item['brand']}")
    if item.get("colors"):
        lines.append(f"Colors: {', '.join(item['colors'])}")
    if item.get("style_tags"):
        lines.append(f"Style: {', '.join(item['style_tags'])}")
    lines.append("")
    lines.append(item["description"])
    return "\n".join(lines)


# ── interface ─────────────────────────────────────────────────────────────────

EXAMPLE_QUERIES = [
    "vintage graphic tee under $30",
    "90s track jacket in size M",
    "flowy midi skirt under $40",
    "black combat boots size 8",
    "designer ballgown size XXS under $5",   # deliberate no-results test
]

def build_interface():
    with gr.Blocks(title="FitFindr") as demo:
        # The user's wardrobe persists across page loads via browser
        # localStorage. New users start with the empty-wardrobe template.
        my_wardrobe_state = gr.BrowserState(
            get_empty_wardrobe(),
            storage_key="fitfindr_wardrobe",
        )
        # Holds the most recently surfaced listing so the keep button can
        # find it without re-running the query.
        selected_item_state = gr.State(None)

        gr.Markdown("""
# FitFindr 🛍️
Find secondhand pieces and get outfit ideas based on your wardrobe.
Describe what you're looking for — include size and price if you want to filter.
        """)

        with gr.Row():
            query_input = gr.Textbox(
                label="What are you looking for?",
                placeholder="e.g. vintage graphic tee under $30, size M",
                lines=2,
                scale=3,
            )
            wardrobe_choice = gr.Radio(
                choices=["My wardrobe", "Example wardrobe"],
                value="My wardrobe",
                label="Style outfits using…",
                scale=1,
            )

        submit_btn = gr.Button("Find it", variant="primary")

        with gr.Row():
            listing_output = gr.Textbox(
                label="🛍️ Top listing found",
                lines=8,
                interactive=False,
            )
            outfit_output = gr.Textbox(
                label="👗 Outfit idea",
                lines=8,
                interactive=False,
            )
            fitcard_output = gr.Textbox(
                label="✨ Your fit card",
                lines=8,
                interactive=False,
            )

        with gr.Row():
            keep_btn = gr.Button("➕ Keep this item", variant="secondary")
            keep_status = gr.Markdown("")
            wardrobe_count_md = gr.Markdown(_wardrobe_count_md(get_empty_wardrobe()))

        gr.Examples(
            examples=[[q, "My wardrobe"] for q in EXAMPLE_QUERIES],
            inputs=[query_input, wardrobe_choice],
            label="Try these queries",
        )

        # On page load, refresh the wardrobe count from whatever
        # BrowserState restored from localStorage.
        demo.load(
            fn=_wardrobe_count_md,
            inputs=[my_wardrobe_state],
            outputs=[wardrobe_count_md],
        )

        submit_btn.click(
            fn=handle_query,
            inputs=[query_input, wardrobe_choice, my_wardrobe_state],
            outputs=[
                listing_output,
                outfit_output,
                fitcard_output,
                selected_item_state,
                wardrobe_count_md,
            ],
        )
        query_input.submit(
            fn=handle_query,
            inputs=[query_input, wardrobe_choice, my_wardrobe_state],
            outputs=[
                listing_output,
                outfit_output,
                fitcard_output,
                selected_item_state,
                wardrobe_count_md,
            ],
        )

        keep_btn.click(
            fn=handle_keep,
            inputs=[my_wardrobe_state, selected_item_state],
            outputs=[my_wardrobe_state, keep_status, wardrobe_count_md],
        )

    return demo


if __name__ == "__main__":
    _setup_logging()
    demo = build_interface()
    demo.launch()
