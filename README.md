# FitFindr — Starter Kit

This starter kit contains everything you need to begin Project 2.

## What's Included

```
ai201-project2-fitfindr-starter/
├── data/
│   ├── listings.json          # 40 mock secondhand listings
│   └── wardrobe_schema.json   # Wardrobe format + example wardrobe
├── utils/
│   └── data_loader.py         # Helper functions for loading the data
├── planning.md                # Your planning template — fill this out first
└── requirements.txt           # Python dependencies
```

## Setup

```bash
pip install -r requirements.txt
```

Set your Groq API key in a `.env` file (get a free key at [console.groq.com](https://console.groq.com)):
```
GROQ_API_KEY=your_key_here
```

## The Mock Listings Dataset

`data/listings.json` contains 40 mock secondhand listings across categories (tops, bottoms, outerwear, shoes, accessories) and styles (vintage, y2k, grunge, cottagecore, streetwear, and more).

Each listing has: `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, and `platform`.

Load it with:
```python
from utils.data_loader import load_listings
listings = load_listings()
```

## The Wardrobe Schema

`data/wardrobe_schema.json` defines the format your agent uses to represent a user's existing wardrobe. It includes:

- `schema`: field definitions for a wardrobe item
- `example_wardrobe`: a sample wardrobe with 10 items you can use for testing
- `empty_wardrobe`: a starting template for a new user

Load an example wardrobe with:
```python
from utils.data_loader import get_example_wardrobe
wardrobe = get_example_wardrobe()
```

## Where to Start

1. **Read `planning.md` and fill it out before writing any code.**
2. Verify the data loads correctly by running `python utils/data_loader.py`.
3. Build and test each tool individually before connecting them through your planning loop.

Your implementation files go in this same directory. There's no required file structure for your agent code — organize it however makes sense for your design.

## Run the App

```bash
python app.py                          # Launch the Gradio UI
FITFINDR_LOG_LEVEL=DEBUG python app.py # Verbose trace through tools + agent
pytest tests/                          # Run the test suite (29 tests)
```

## Stretch Features Implemented

- **Style profile memory.** The user's wardrobe persists across sessions in browser localStorage via `gr.BrowserState(storage_key="fitfindr_wardrobe")`. On return visits, previously-kept items are restored automatically — the user never has to re-describe their wardrobe. The "➕ Keep this item" button appends the most recently surfaced listing through the pure `update_style_profile(new_item, wardrobe) → wardrobe` tool, and Gradio syncs the result back to localStorage. See **State Management** below for the data flow.
- **Retry logic with fallback (visible to the user).** If `search_listings` returns no matches AND a size was specified, `run_agent` retries once without the size filter (per planning step 3). When that retry succeeds, the agent writes a one-line note to `session["search_note"]` (e.g., `"No exact match for size 8 — showing the closest result regardless of size."`) and the Gradio handler prepends it with an ℹ️ to the listing panel — so the user sees the relaxed-filter result and knows _why_ it doesn't exactly match their query. When the retry also returns nothing, the error message itself explicitly says "(Also tried without the size filter — still nothing matched.)".

## Tool Inventory

| Tool | Inputs | Output | Purpose |
|---|---|---|---|
| `search_listings` | `description: str`, `size: str \| None`, `max_price: float \| None` | `list[dict]` — top 3 by BM25 (or `[]`) | Filter listings by price + size, rank by BM25 relevance to the description |
| `suggest_outfit` | `new_item: dict`, `wardrobe: dict` | `str` | LLM-generated outfit naming wardrobe pieces (or general advice if wardrobe is empty) |
| `create_fit_card` | `outfit: str`, `new_item: dict` | `str` | Short OOTD-voice caption mentioning item name/price/platform; high temp for variety |
| `update_style_profile` | `new_item: dict`, `wardrobe: dict` | `dict` — updated wardrobe | Pure-function append of a listing as a wardrobe item with a fresh `w_NNN` id; caller persists |

## Planning Loop

`run_agent(query, wardrobe)` runs six sequential steps inside a `try/finally` so end-of-run session state is always logged:

1. **Init session** — fresh dict with `query`, `wardrobe`, and placeholder fields for downstream results.
2. **Parse query (LLM)** — extract `{description, size, max_price}` via Groq with `response_format=json_object`; malformed output → `session['error']`, return early.
3. **Search listings** — call `search_listings(...)`. If 0 results AND a size was specified, retry once without the size filter. Still 0 → set error, return early.
4. **Select top result** → `session['selected_item']`.
5. **Suggest outfit** — pass selected item + wardrobe to `suggest_outfit`.
6. **Create fit card** — pass outfit + selected item to `create_fit_card`.

Every LLM-using step can raise `ToolError`; the loop catches and writes `str(e)` to `session['error']` before returning early.

## State Management

Two layers:

- **Per-interaction**: the `session` dict flows top-down through `run_agent` — `query`, `parsed`, `wardrobe`, `search_results`, `selected_item`, `outfit_suggestion`, `fit_card`, `search_note` (set when the retry relaxed a filter), and `error`. Each step reads prior values and writes its own. Final session is logged on every exit path — INFO summary + DEBUG full dump (minus `wardrobe`).
- **Cross-session**: the user's wardrobe persists in browser localStorage via `gr.BrowserState(storage_key="fitfindr_wardrobe")`. The "➕ Keep this item" button calls `update_style_profile` (pure dict-in → dict-out) and writes the result back to BrowserState, which Gradio syncs to localStorage automatically.

## Error Handling

| Tool | Failure mode | Behavior | Concrete test |
|---|---|---|---|
| `search_listings` | Dataset load fails | `raise ToolError("Failed to load listings...")` | `test_raises_tool_error_when_dataset_missing` monkeypatches `tools.load_listings` to raise `FileNotFoundError`; asserts `ToolError` propagates |
| `search_listings` | Query matches nothing | Return `[]` (NOT a raise) | `test_no_match_returns_empty_list("xyzzy spaceship laser unicorn")` → agent retries without size, then sets `session['error']` |
| `suggest_outfit` | Wardrobe is empty | Fall back to general styling advice (NOT a raise) | `test_empty_wardrobe_returns_general_advice` with `get_empty_wardrobe()` |
| `suggest_outfit` | LLM call fails | `raise ToolError("suggest_outfit LLM call failed: ...")` | `test_llm_failure_raises_tool_error` monkeypatches `_get_groq_client` to a broken client |
| `create_fit_card` | Empty outfit | Return placeholder string `"⚠️ Couldn't generate a fit card..."` (NOT a raise — fit card is non-critical) | `test_empty_outfit_returns_placeholder_string` parametrized over `["", "   ", "\n\t"]` |
| `create_fit_card` | `new_item` missing title/price/platform | `raise ToolError("missing required field(s): X")` | `test_missing_required_field_raises_tool_error` parametrized over each field |
| `update_style_profile` | `new_item` missing `title` | `raise ToolError("missing required field 'title'")` | `test_missing_title_raises_tool_error` |

## Spec Reflection

What changed between `planning.md` and the final code:

- **Tool 4 signature.** Planning had `update_style_profile(new_item)` doing both the transform AND localStorage I/O. Final tool is pure `update_style_profile(new_item, wardrobe) → wardrobe`; the Gradio handler owns persistence via `gr.BrowserState`. Easier to test, separates concerns.
- **Error returns → exceptions.** Planning originally specified tools return `{"error": "..."}` dicts on failure. Final convention is `raise ToolError`; agent loop catches and writes to `session['error']`. Cleaner signatures (one return shape per tool), errors explicit at the call site.
- **Empty-outfit on `create_fit_card`.** Originally specced as a `ToolError` like the others; dropped to a graceful placeholder string — the fit card is non-critical, so it shouldn't fail the whole interaction.
- **Search relevance scoring.** Started as token-overlap counting (what the planning TODO suggested), then swapped to BM25 after a real query (`"black combat boots size 8"`) surfaced an Oversized Flannel Shirt instead of the Suede Chelsea Boots.
- **Step 1 wardrobe load.** Planning step 1 had the agent load the wardrobe from browser storage. Final design: `run_agent` takes `wardrobe` as a parameter; the Gradio handler owns the read-from-BrowserState step. Keeps the agent UI-agnostic.

## AI Usage

### Instance 1 — `search_listings` implementation + BM25 swap

**Input to AI:** the Tool 1 spec block from `planning.md` (inputs, return format, failure mode), a pointer to `load_listings()`, and the instruction to write at least one pytest test per documented failure mode.

**AI produced:** a token-overlap scorer — tokenized the query and each listing's title/description/style_tags, dropped stopwords, scored by `|query_tokens ∩ listing_tokens|`, sorted descending, capped at 3 with `[]` on no-match. Wrote pytest tests covering happy path + the 0-results failure mode.

**What I changed before using:**

1. After a smoke test, I noticed `"shoes US 8"` returned nothing because `shoes` was a category name, not a description token. I had the AI add `category` to the searchable haystack.
2. Later, `"black combat boots size 8"` returned an Oversized Flannel Shirt instead of the Suede Chelsea Boots — the overlap counter treated every matched token equally, so a single match on the common token `black` outranked nothing-else-available. I overrode the entire scoring approach: had the AI swap in BM25 via `rank_bm25` so IDF weighting makes rare tokens (`boots`) beat common ones (`black`). The pre-filter, top-3 cap, and `[]`-on-no-match contract stayed.

### Instance 2 — `create_fit_card` error convention

**Input to AI:** the Tool 3 spec block from `planning.md`, the example fit-card text from "A Complete Interaction" (`"thrifted this faded band tee off depop for $22..."`) as a tone reference, and the shared "tools raise `ToolError` on failure" convention we'd settled on earlier in the session.

**AI produced:** a `create_fit_card` that raised `ToolError` on three failure modes: empty/whitespace outfit, missing required `new_item` fields (title/price/platform), and LLM call failure. Wrote parametrized tests for each.

**What I changed before using:** I overrode the empty-outfit branch — the fit card is non-critical to the user's experience, so it should degrade gracefully rather than fail the whole interaction. The AI updated `tools.py` (return `"⚠️ Couldn't generate a fit card..."` instead of raising), the Tool 3 spec in `planning.md`, the Error Handling table (split into two rows for `create_fit_card`), the architecture diagram (step 6 now annotates "str returned (incl. placeholder on empty outfit, NOT a raise)"), and the test (renamed `test_empty_outfit_raises_tool_error` → `test_empty_outfit_returns_placeholder_string`, asserting a non-empty descriptive string instead of `pytest.raises`).
