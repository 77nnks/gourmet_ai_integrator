# CLAUDE.md — Gourmet AI Integrator

This file provides guidance for AI assistants (Claude and others) working in this codebase.

---

## Project Overview

**Gourmet AI Integrator** is a multi-platform restaurant discovery and management bot that integrates:

- **Discord** and **LINE** chat interfaces
- **Google Places API** for restaurant data
- **OpenAI GPT-4o-mini** for AI-powered analysis and enrichment
- **Notion** as a persistent restaurant database

Users can search for restaurants, get AI-generated summaries and tags, save records to Notion, and get location-based recommendations — all from within Discord or LINE.

---

## Repository Structure

```
gourmet_ai_integrator/
├── main.py                    # Entry point: starts Discord (thread) + LINE (Flask)
├── Procfile                   # Deployment config (Railway/Heroku): `web: python main.py`
├── requirements.txt           # Python dependencies (no pinned versions)
│
├── bot_discord/
│   └── discord_bot.py         # Discord slash command bot (266 lines)
│
├── bot_line/
│   └── line_bot.py            # LINE webhook Flask server (725 lines)
│
└── modules/
    ├── __init__.py             # Barrel exports for module functions
    ├── ai_processing.py        # OpenAI GPT-4o-mini wrappers
    ├── google_api.py           # Google Places / Geocoding API calls
    ├── notion_client.py        # Notion database CRUD operations
    └── utils.py                # Shared helpers (icons, distance, formatting)
```

---

## Architecture

### Startup Flow (`main.py`)

1. Discord bot is started in a **daemon thread** (`start_discord_bot()`)
2. LINE Flask app runs on the **main thread** (port from `PORT` env var, default `8080`)
3. Both bots share the same `modules/` layer

### Module Responsibilities

| Module | Responsibility |
|---|---|
| `ai_processing.py` | All OpenAI API calls; returns structured JSON |
| `google_api.py` | Google Places TextSearch + Details; Geocoding |
| `notion_client.py` | Notion database read/write (upsert by `place_id`) |
| `utils.py` | Photo URLs, store-type icons, rating stars, price text, Haversine distance |

### Data Flow (Save a Restaurant)

```
User command → Google Places search → Candidate selection
    → Google Places Details → OpenAI analysis (summary, type, recs, tags)
    → Notion upsert (by place_id to prevent duplicates)
    → Confirmation message to user
```

---

## Key Features

### Discord Bot (`bot_discord/discord_bot.py`)

**Slash Commands:**
- `/save <query> [comment]` — Search, AI-enrich, and save a restaurant to Notion
- `/nearby <location> [conditions]` — Find saved restaurants near a location, scored by distance/rating/conditions

**UI Patterns:**
- Discord `app_commands` (slash commands)
- `discord.ui.View` + `discord.ui.Button` for candidate selection
- `discord.Embed` for rich result display
- `interaction.response.defer()` to avoid timeout on long operations

### LINE Bot (`bot_line/line_bot.py`)

**Conversation Modes (state machine per user):**
- `search` — Text-based restaurant search
- `recommend` — Location-based recommendation (accepts GPS coordinates)
- `await_save` — Waiting for user to confirm save
- `waiting_comment` — Waiting for optional comment before save

**State management:**
```python
user_state = {}  # Dict keyed by user_id; stores mode and pending data
```

**UI Patterns:**
- LINE Flex Messages (Bubble + Carousel) for rich layouts
- Postback actions for button-driven state transitions
- `push_message` in a thread for async response (prevents webhook timeout)
- Location message support (GPS coordinates from LINE app)

---

## External Services & Required Environment Variables

All secrets are loaded via `python-dotenv` from a `.env` file (not committed to repo).

| Variable | Service | Used In |
|---|---|---|
| `GOOGLE_API_KEY` | Google Places + Geocoding | `google_api.py` |
| `OPENAI_API_KEY` | OpenAI GPT-4o-mini | `ai_processing.py` |
| `DISCORD_BOT_TOKEN` | Discord API | `discord_bot.py` |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Messaging API | `line_bot.py` |
| `LINE_CHANNEL_SECRET` | LINE webhook verification | `line_bot.py` |
| `NOTION_API_KEY` | Notion API | `notion_client.py` |
| `MAIN_DATABASE_ID` | Notion database target | `notion_client.py` |
| `PORT` | Flask server port | `main.py` (default: `8080`) |

---

## Notion Database Schema

The Notion database (`MAIN_DATABASE_ID`) has the following property structure:

| Property Name (Japanese) | Type | Description |
|---|---|---|
| 店名 | Title | Restaurant name |
| 住所 | Rich Text | Address |
| 営業時間 | Rich Text | Business hours |
| 感想 | Rich Text | User comment |
| サブタイプ | Rich Text | Store subtype (AI-inferred) |
| 印象 | Rich Text | AI-generated impression summary |
| 評価 | Number | Google rating (0–5) |
| 料金 | Number | Google price level (0–4) |
| lat / lng | Number | Coordinates |
| URL | URL | Google Maps URL |
| 公式サイト | URL | Official website |
| 店タイプ | Select | Store type (AI-inferred) |
| Tags | Multi-select | AI-generated tags |
| おすすめメニュー | Rich Text | AI-recommended dishes |
| place_id | Rich Text | Google Place ID (used as unique key) |

---

## AI Processing (`ai_processing.py`)

All OpenAI calls use `gpt-4o-mini` and force JSON output (`response_format={"type": "json_object"}`).

| Function | Input | Output (JSON keys) |
|---|---|---|
| `summarize_reviews(reviews)` | List of review texts | `positive`, `negative`, `conclusion` |
| `infer_store_type(types, summary)` | Google types list + summary | `store_type`, `sub_type` |
| `infer_recommendation(types, summary, name)` | Same + name | `recommendations` (list of 3) |
| `classify_tags(name, types, summary)` | Same | `tags` (list of strings) |

All functions have the pattern: build a prompt → call `_request_json(prompt)` → return parsed dict.

---

## Conventions and Patterns

### Language

- **UI strings**: Japanese (user-facing messages, Notion field names)
- **Code**: English (function names, variable names, comments mostly in English)
- **Emoji**: Used extensively in user-facing messages (📍, 🔍, 🍽️, ☕, 🍣, etc.)

### Naming

- Python snake_case for functions and variables
- Module-level dicts for constants (icon maps, tag maps)
- Private helpers prefixed with underscore: `_request_json`, `_headers`

### Async / Threading

- Discord: use `await interaction.response.defer()` before any long operation; then `interaction.followup.send()`
- LINE: use `threading.Thread(target=...).start()` for operations that would exceed webhook timeout
- Discord bot itself started as a daemon thread from `main.py`

### Error Handling

- API errors are caught at the bot layer and return user-friendly messages
- `find_page_by_place_id` prevents Notion duplicate entries (idempotent upserts)
- State cleanup on cancel commands: `user_state.pop(user_id, None)`

### Google Places

- Search uses `language=ja` for Japanese results
- Details request includes: `name`, `formatted_address`, `geometry`, `rating`, `opening_hours`, `price_level`, `reviews`, `types`, `url`, `website`, `photos`
- Photos are fetched via `utils.get_photo_url(photo_reference, max_width=400)`

---

## Development Workflow

### Running Locally

1. Copy `.env` with all required environment variables (see table above)
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the application:
   ```bash
   python main.py
   ```
4. For LINE bot: expose local Flask server via ngrok or similar, then set webhook URL in LINE Developers console

### Deployment

Deployed to **Railway** or **Heroku** via `Procfile`:
```
web: python main.py
```
- Set all environment variables in the platform dashboard
- The LINE webhook URL must be publicly accessible

### Adding New Features

- **New Discord command**: Add a new `@tree.command` in `discord_bot.py`; use `defer()` for long ops
- **New LINE flow**: Add a new mode string to `user_state`, handle in the `handle_message` function
- **New AI analysis**: Add a function to `ai_processing.py` following the `_request_json` pattern
- **New Notion field**: Update the property dict in `notion_client.py` `upsert_store` function

### No Tests Currently

The project has no automated tests. When adding features:
- Manually test via the respective chat interface
- For Notion writes, verify entries in the Notion database directly
- Consider adding `pytest` tests for pure functions in `utils.py` and `ai_processing.py`

---

## Dependencies

```
Flask            # Web framework for LINE webhook
line-bot-sdk     # LINE Messaging API client
discord.py       # Discord bot framework
requests         # HTTP client for Google/Notion APIs
openai           # OpenAI API client
python-dotenv    # .env file loading
```

Versions are **not pinned** in `requirements.txt`. Pin versions if reproducibility becomes important.

---

## Common Gotchas

1. **LINE webhook timeout**: LINE requires a response within 3 seconds. Long operations (AI + Notion writes) must be done in a background thread with `push_message` instead of `reply_message`.

2. **Discord interaction timeout**: Must call `defer()` within ~3 seconds, then use `followup.send()` after processing.

3. **Notion duplicate prevention**: Always use `find_page_by_place_id` before saving — the upsert function handles insert vs update automatically.

4. **Google Places photo URL**: Photos require the API key in the URL. Use `utils.get_photo_url()` — do not construct URLs manually.

5. **PORT variable**: Railway/Heroku inject `PORT` dynamically. The default `8080` is for local dev only.

6. **Japanese locale**: Google Places queries use `language=ja`. Changing this will affect AI analysis prompts which expect Japanese review text.
