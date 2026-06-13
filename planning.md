# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
This tool filters a list of secondhand item listings by item description, optional size and optional price limit. It returns 3 matching listings sorted by relevance. 

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `description` (str): a brief description of the item to search for (e.g. `'vintage jeans'`)
- `size` (str): size of the item, may be of varying units (e.g. `'US 8'`, `'S/M'`, `'One Size'`, `'W27'`)
- `max_price` (float): the budget limit (in USD) - only return item(s) with listed price(s) lower than this

**What it returns:**
<!-- Describe the return value — what fields does a result contain? -->
A list containing 3 top matching listings, sorted by relevance, in the following format:
```
[
  {
    "id": "lst_033",
    "title": "Vintage Band Tee — Faded Grey",
    "description": "Faded grey band-style tee with distressed graphic. Crew neck. Fits boxy. Well-loved but no holes or major damage.",
    "category": "tops",
    "style_tags": ["vintage", "grunge", "band tee", "graphic tee", "streetwear"],
    "size": "L",
    "condition": "fair",
    "price": 19.00,
    "colors": ["grey", "charcoal"],
    "brand": null,
    "platform": "depop"
  },
  {
    "id": "lst_002",
    "title": "Y2K Baby Tee — Butterfly Print",
    "description": "Super cute early 2000s baby tee with butterfly graphic. Fitted crop length. Tag says medium but fits like a small.",
    "category": "tops",
    "style_tags": ["y2k", "vintage", "graphic tee", "cottagecore"],
    "size": "S/M",
    "condition": "excellent",
    "price": 18.00,
    "colors": ["white", "pink", "purple"],
    "brand": null,
    "platform": "depop"
  },
  {
    "id": "lst_006",
    "title": "Graphic Tee — 2003 Tour Bootleg Style",
    "description": "Vintage-style bootleg tee with faded graphic. Slightly boxy fit. 100% cotton, soft and worn-in.",
    "category": "tops",
    "style_tags": ["graphic tee", "vintage", "grunge", "streetwear", "band tee"],
    "size": "L",
    "condition": "good",
    "price": 24.00,
    "colors": ["black"],
    "brand": null,
    "platform": "depop"
  },
]
```

**What happens if it fails or returns nothing:**
<!-- What should the agent do if no listings match? -->
It automatically retries with loosened constraints (e.g., remove size filter) and informs the user (e.g. set a log message in the session) what was adjusted.
If the retry fails, then it should return an error response in the form of `{"error": "<error message>"}`.

---

### Tool 2: suggest_outfit

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
This tool takes an item the current user is considering to thrift and their wardrobe, and call the LLM to generate outfit suggestion. 

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `new_item` (dict): details of a listing item the user is considering to thrift, for which the tool needs to give complete outfit styling advice.
- `wardrobe` (dict): contains a list of items in a wardrobe (by fetching `wardrobe['items']`) , based on which the tool uses to guess the user's style profile as context for its outfit styling suggestion. 

**What it returns:**
<!-- Describe the return value -->
It returns a non-empty string of a complete outfit styling suggestion based on the given item and the user's style profile based on the given wardrobe.

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the wardrobe is empty or no outfit can be suggested? -->
If the wardrobe given is empty, it tries to guess the user's style from the user's query recorded in the session dict. If the query has no information about the user's style, either, or no outfit can be suggested, it can fall back to giving general styling advice.
If the LLM fails or any unexpected error, it should return an error response in the form of `{"error": "<error message"}`.

---

### Tool 3: create_fit_card

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
This tool takes a string of outfit styling suggestion and information about a thrift item, and calls the LLM to generate a shareable outfit description.

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `outfit` (str): description of a complete outfit styling recommendation 
- `new_item` (dict): details of a listing item that the user is considering thrifting

**What it returns:**
<!-- Describe the return value -->
A non-empty string of a shareable outfit description.

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the outfit data is incomplete? -->
The fit card content would just be more generic as the outfit suggestion is likely general styling advice.
If the LLM fails or any unexpected error, it should return an error response in the form of `{"error": "<error message"}`.

---

### Tool 4: update_style_profile

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
This tool adds a new thrift item to the wardrobe stored in the current user's browser local storage. If the current user has no existing wardrobe, it creates one following the schema defined in ./data/wardrobe_schema.json and add the item to that.
The item must be formatted as described in the wardrobe_schema. For example:
```
      {
        "id": "w_008",
        "name": "Black combat boots",
        "category": "shoes",
        "colors": ["black"],
        "style_tags": ["boots", "grunge", "classic"],
        "notes": "Lace-up, mid-ankle height"
      }
```

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `new_item` (dict): details of a listing item that the user is considering thrifting

**What it returns:**
<!-- Describe the return value -->
The updated wardrobe JSON with the new item added. For example:
```
{
  "my_wardrobe": {
    "items": [
      {
        "id": "w_001",
        "name": "Baggy straight-leg jeans, dark wash",
        "category": "bottoms",
        "colors": ["dark blue", "indigo"],
        "style_tags": ["denim", "streetwear", "baggy"],
        "notes": "High-waisted, sits above the hip"
      },
      {
        "id": "w_008",
        "name": "Black combat boots",
        "category": "shoes",
        "colors": ["black"],
        "style_tags": ["boots", "grunge", "classic"],
        "notes": "Lace-up, mid-ankle height"
      }
    ]
  }
}
```

**What happens if it fails or returns nothing:**
If any unexpected error, it should return an error response in the form of `{"error": "<error message"}`.

---

## Planning Loop

**How does your agent decide which tool to call next?**
<!-- Describe the logic your planning loop uses. What does it look at? What conditions change its behavior? How does it know when it's done? -->

For a single user interaction:
0. Initialize a new session dict to manage the state of the new interaction. Store the original user query in `session['query']`.
1. Check if the current user's browser local storage has an existing wardrobe dict. If no existing wardrobe, fetch an empty one using `get_empty_wardrobe()`. Store the wardrobe in `session['wardrobe']`. 
2. Parse the given natural language user request (e.g. "I'm looking for a vintage graphic tee under $30, size M. I mostly wear baggy jeans and chunky sneakers.") to extract a dict of the description, size and max_price by calling to the LLM. 
Example parsed result:
```
{
    "description": "vintage graphic tee",
    "size": "M",
    "max_price": 30.00
}
```
Store the result in `session['parsed']`.
If there is any error or the LLM returns an empty or malformed dict (e.g. LLM not working or user query was not about fit finding and no relevant information could be extracted), set `session['error']` to a helpful message (e.g. "Failed to parse user's request: <error>. Returned: <parsed result>.") and return early.
3. Call `search_listings` with the parsed parameters. Store the result in `session['search_results']`.
If no results, automatically retry once with loosened constraints (e.g., remove size filter) and inform the user what was adjusted.
If still no results after the retry, set `session[error]` to a helpful message and return early. Do NOT proceed to `suggest_outfit()` with empty input.
4. Select the item to use (e.g., the top result). Store it in `session['selected_item']`.
5. Call `suggest_outfit()` with the selected item and wardrobe. Store the result in `session['outfit_suggestion']`.
6. Call `create_fit_card()` with the outfit suggestion and selected item. Store the result in `session['fit_card']`.
7. Check with the user if they want to keep the selected item. If yes, call `update_style_profile()` to add the item to `session['wardrobe']` and update the user's locally stored wardrobe (in user browser).
8. Return the session.

---

## State Management

**How does information from one tool get passed to the next?**
<!-- Describe how your agent stores and accesses state within a session. What data is tracked? How is it passed between tool calls? -->
    
FitFindr stores and accesses state within a session using a `session` dict that it initializes at the start of a session. The session contains the following data:
```
{
    "query": query,              # original user query
    "parsed": {},                # extracted description / size / max_price
    "search_results": [],        # list of top 3 matching listing dicts returned by search_listings
    "selected_item": None,       # top result, passed into suggest_outfit
    "wardrobe": wardrobe,        # user's wardrobe dict fetched from the user browser or initialized with get_empty_wardrobe
    "outfit_suggestion": None,   # string returned by suggest_outfit
    "fit_card": None,            # string returned by create_fit_card
    "error": None,               # set if the interaction ended early or if any of the tool calls returns an error response
}
```

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Automatically retry once and if still no results, set a helpful message in `session['error']` and return early |
| suggest_outfit | Wardrobe is empty | Fetch the user's original query from `session['query']` as context and calls the LLM to generate styling advice with the given context |
| create_fit_card | Outfit input is missing or incomplete | Pass the incomplete input to the tool call anyway and let its LLM generate content the best it can |

---

## Architecture

<!-- Draw a diagram of your agent showing how the components connect:
     User input → Planning Loop → Tools (search_listings, suggest_outfit, create_fit_card)
                                                                          ↕
                                                                   State / Session
     Show what triggers each tool, how state flows between them, and where error paths branch off.
     ASCII art, a Mermaid diagram (https://mermaid.js.org/syntax/flowchart.html), or an embedded
     sketch are all fine. You'll share this diagram with an AI tool when asking it to implement
     the planning loop and each individual tool. -->

---

## AI Tool Plan

<!-- For each part of the implementation below, describe:
     - Which AI tool you plan to use (Claude, Copilot, ChatGPT, etc.)
     - What you'll give it as input (which sections of this planning.md, your agent diagram)
     - What you expect it to produce
     - How you'll verify the output matches your spec before moving on

     "I'll use AI to help me code" is not a plan.
     "I'll give Claude my Tool 1 spec (inputs, return value, failure mode) and ask it to implement
     search_listings() using load_listings() from the data loader — then test it against 3 queries
     before trusting it" is a plan. -->

**Milestone 3 — Individual tool implementations:**

**Milestone 4 — Planning loop and state management:**

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1:**
<!-- What does the agent do first? Which tool is called? With what input? -->  
FitFindr calls the `search_listings`  tool with `("vintage graphic tee", size="M", max_price=30.0)`. The search tool returns top 3 matching listings, based on which FitFindr picks the top result: "Faded Band Tee — $22, Depop, Good condition."

If `search_listings` returns no results, automatically retry once with loosened constraints (e.g., remove size filter) and inform the user what was adjusted.

If after retry, FitFindr can't still find any matching item, it should inform the user of the result and ask the user what to do instead.

**Step 2:**
<!-- What happens next? What was returned from step 1? What tool is called now? -->
If Step 1 returns a specific item, FitFindr next checks if the current user has an existing wardrobe, and if not, it just grabs an empty wardrobe. 
Given the item returned from Step 1 (`'Faded Band Tee'`) and the current user's wardrobe, FitFindr then calls the `suggest_outfit` tool with `(new_item=<band tee>, wardrobe=<user's wardrobe>)`. In this interaction, the current user's wardrobe is empty, so the tool just returns general styling advice based on the user's query: "Pair this with your wide-leg jeans and platform Docs for a classic 90s grunge look. Roll the sleeves once and tuck the front corner slightly for shape." 

**Step 3:**
<!-- Continue until the full interaction is complete -->
FitFindr answers the user with the matching item found from Step 1 and the suggested outfit from Step 2: "I found a Faded Band Tee, Depop in Good condition for $22! Pair this with your wide-leg jeans and platform Docs for a classic 90s grunge look. Roll the sleeves once and tuck the front corner slightly for shape."

FitFindr then asks the user if they would like to keep this item. If yes, it then calls the `update_style_profile` tool to add the item to the current user's wardrobe. If not, it asks the user what to do next. 
In this interaction, the user wants to keep the item.

**Final output to user:**
<!-- What does the user actually see at the end? -->
Given the suggested outfit returned from Step 2 and the item returned from Step 1, FitFindr now calls the `create_fit_card` tool with `(outfit=<suggestion>, new_item=<band tee>)`. It can then give the final output: "Great choice! Here's a quick shareable outfit card for you: "thrifted this faded band tee off depop for $22 and honestly it was made for my wide-legs 🖤 full look in my stories". Show off your new outfit!"

