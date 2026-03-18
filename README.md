# Wasteless Coffee Dial-in Assistant (WCDA)

An AI-powered Discord bot and MCP server for coffee enthusiasts. Upload a photo of your coffee bag to get personalized grind setting recommendations, or search for equipment using natural language queries. Features web scraping, vector search, and integration with AI agents.

## Features

- **Image Analysis**: Uses Google Gemini Vision API to extract coffee details (roaster, origin, process, roast level) from bag photos.
- **RAG Recommendations**: Searches your PostgreSQL database for similar coffees and suggests optimal grind settings, dose, and brewing tips.
- **Equipment Discovery**: Semantic search for coffee equipment using natural language queries (e.g., "quiet flat burr grinder for espresso").
- **Web Scraping**: Automatically scrape and extract equipment data from online stores using AI.
- **Vector Database**: Powered by pgvector for fast similarity searches on both coffee logs and equipment.
- **Feedback Loop**: React with 👍 to provide the actual grind setting you used (based on experience), which is saved back to the database for improved future recommendations.
- **MCP Server**: Integrate with AI agents (like Claude) for coffee dial-in assistance.
- **Docker Ready**: Fully containerized for easy deployment on Linux servers.

## Project Structure

```
wasteless-coffee-dial-in-assistant/
├── src/                    # Source code
│   ├── core/              # Main applications
│   │   ├── discord_bot.py # Discord bot
│   │   ├── mcp_server.py # MCP server for AI agents
│   │   └── main.py        # CLI interface
│   ├── ai/                # AI/ML functionality
│   │   ├── vision.py      # Image analysis
│   │   ├── rag.py         # RAG recommendations
│   │   └── vector_search.py # Vector search
│   ├── database/          # Database models and utilities
│   │   ├── database.py    # DB connection
│   │   ├── models.py      # SQLAlchemy models
│   │   ├── init_db.py     # DB initialization
│   │   ├── seed.py        # Sample data
│   │   └── view_db.py     # DB viewer
│   └── scraping/          # Web scraping tools
│       ├── scraper.py     # Scraping logic
│       └── add_equipment.py # Equipment processing
├── config/                # Configuration files
├── data/                  # Data files (URLs, test images)
├── Dockerfile             # Docker build
├── docker-compose.yml     # Docker services
├── requirements.txt       # Python dependencies
└── README.md             # This file
```

## Setup

### 1. Clone the Repository
```bash
git clone https://github.com/galdavido/Wasteless-Coffee-Dial-in-Assistant.git
cd Wasteless-Coffee-Dial-in-Assistant
```

### 2. Environment Configuration
Create a `.env` file in the root directory.

> `.venv` is intentionally excluded from git and Docker context. New users do **not** need your local virtual environment—Python is provided by the pinned Docker image (`3.14.3`) and dependencies are installed from `requirements.txt` during image/build setup.

For the root `docker-compose.yml` workflow (running from your host machine), use:
```env
POSTGRES_USER=barista
POSTGRES_PASSWORD=supersecret
POSTGRES_DB=barista_db
DATABASE_URL=postgresql://barista:supersecret@localhost:5434/barista_db
GEMINI_API_KEY=your_gemini_api_key_here
DISCORD_TOKEN=your_discord_bot_token_here
```

- **GEMINI_API_KEY**: Get from [Google AI Studio](https://makersuite.google.com/app/apikey).
- **DISCORD_TOKEN**: Create a bot at [Discord Developer Portal](https://discord.com/developers/applications). Enable "Message Content Intent" and set permissions for Send Messages, Read Message History, Add Reactions.

If you use the VS Code Dev Container workflow, the database hostname is different inside the container network:

```env
DATABASE_URL=postgresql://barista:supersecret@db:5432/barista_db
```

### 3. Build and Run with Docker
```bash
docker-compose up --build -d
```

This starts:
- PostgreSQL database on port 5434
- WCDA bot (auto-initializes DB and seeds sample data)

Check logs:
```bash
docker-compose logs -f wcda-bot
```

### 4. Invite the Bot to Your Server
- In Discord Developer Portal > OAuth2 > URL Generator:
  - Scopes: `bot`
  - Permissions: Send Messages, Read Message History, Add Reactions
- Use the generated URL to invite the bot.

## Usage

### Discord Bot

1. **Upload an Image**: In a Discord channel, attach a photo of your coffee bag (JPG/PNG).
2. **Receive Analysis**: The bot replies with extracted coffee details and grind recommendations from your database.
3. **Provide Feedback**: If the suggestion is good, react with 👍. The bot saves this as a new log entry for future reference.

### Equipment Search

- `!search_equipment <query>` - Search for equipment using natural language (e.g., `!search_equipment quiet espresso grinder`)

### Equipment Setup

Before using the bot, set your espresso equipment so recommendations are tailored to your setup:

- `!set_grinder <brand> <model>` - Set your grinder (e.g., `!set_grinder Kingrinder K6`)
- `!set_machine <brand> <model>` - Set your espresso machine (e.g., `!set_machine AVX Hero Plus 2024`)
- `!show_equipment` - Display your current equipment settings

### MCP Server

The MCP server allows AI agents to access WCDA's coffee analysis capabilities:

```bash
python mcp_server.py
```

This enables AI assistants to analyze coffee bag photos and provide dial-in recommendations programmatically.

The bot will use this information to provide personalized grind recommendations based on your equipment.

## Scraping Equipment Data

To expand your equipment database with data scraped from online stores:

### Single URL
```bash
python add_equipment.py
```
This will scrape the hard-coded test URL and add it to your database.

### Multiple URLs from Code
Modify the `test_urls` list in `add_equipment.py` and run:
```bash
python add_equipment.py
```

### Multiple URLs from File
Create a `urls.txt` file with one URL per line:
```
# URLs to scrape for coffee equipment data
https://example.com/grinder1
https://example.com/machine1
```

Then run:
```bash
python add_equipment.py urls.txt
```

The scraper uses Google Gemini AI to extract structured data (brand, model, features) from product pages and stores them with vector embeddings for semantic search.

## Vector Search

Search your equipment database using natural language:

```bash
python vector_search.py
```

Or integrate the `search_equipment()` function into your applications for AI-powered equipment discovery.

## Code Comments and Architecture

### Key Files
- **`src/core/discord_bot.py`**: Main Discord bot logic using `discord.py`. Handles events like `on_ready` and `on_message`. Processes attachments, calls vision/RAG modules, and manages reactions.
- **`src/core/mcp_server.py`**: MCP server for AI agent integration, exposing coffee analysis tools.
- **`src/core/main.py`**: Command-line interface for testing coffee bag analysis.
- **`src/ai/vision.py`**: Uses Google GenAI to analyze images and extract structured coffee data via Pydantic schema.
- **`src/ai/rag.py`**: Retrieval-Augmented Generation – queries the DB for similar coffees and formats recommendations.
- **`src/ai/vector_search.py`**: Semantic search for equipment using pgvector and cosine similarity.
- **`src/scraping/scraper.py`**: Web scraping utility that extracts equipment data from online stores using AI.
- **`src/scraping/add_equipment.py`**: Processes scraped data, generates embeddings, and saves to the vector database.
- **`src/database/models.py`**: SQLAlchemy ORM models for `Bean`, `Equipment`, `DialInLog`, and `ScrapedEquipment`.
- **`src/database/database.py`**: DB connection setup with SQLAlchemy and pgvector support.
- **`src/database/init_db.py` / `src/database/seed.py`**: Initialize tables and populate sample data.
- **`src/database/view_db.py`**: Utility to display database contents and vector previews.

### Bot Flow
1. **Message Received**: Check for image attachments.
2. **Vision Analysis**: Download image, send to Gemini, parse JSON response.
3. **DB Search**: Query for matching beans (by origin/process), retrieve logs with high ratings.
4. **Response**: Format and send recommendation.
5. **Feedback**: Wait for 👍 reaction, then save new log to DB.

### Vector Search Flow
1. **Query Received**: Convert natural language query to embedding vector.
2. **Similarity Search**: Use pgvector cosine distance to find most similar equipment.
3. **Results**: Return top matches with features and specifications.

### MCP Integration
The MCP server exposes WCDA's capabilities to AI agents:
- `get_coffee_dial_in(image_path)`: Analyze coffee bag photo and return dial-in recommendations.

### Notes
- The bot ignores its own messages to prevent loops.
- Temporary files are cleaned up after processing.
- DB operations use SQLAlchemy sessions for safety.
- Type checking is suppressed for `discord.py` (no stubs) using `# type: ignore`.
- Vector embeddings use 768-dimensional Gemini embeddings for both coffee features and equipment data.

## Troubleshooting

- **Bot not responding?** Check logs: `docker-compose logs wcda-bot`. Ensure token is valid and intents enabled.
- **401 Unauthorized?** Reset Discord token and update `.env`.
- **No recommendations?** Seed data might be missing; run `python seed.py` locally or check DB.
- **Image analysis fails?** Verify Gemini API key and image quality.
- **Permissions issues?** Re-invite bot with correct permissions.

## Development

### Dev Container (Recommended for multi-laptop workflow)

If you use VS Code Dev Containers, most local setup is automatic and consistent across machines.

Prerequisites:
- Docker Desktop
- VS Code
- Dev Containers extension (`ms-vscode-remote.remote-containers`)

Quick start:
1. Clone the repository.
2. Open it in VS Code.
3. Run `Dev Containers: Reopen in Container`.
4. Wait for the initial build and `postCreateCommand` to finish.

What the container sets up:
- Python 3.14.3 development environment
- Project dependencies from `requirements.txt`
- `pre-commit` + installed git hook
- Local PostgreSQL (`pgvector/pgvector:pg15`) available inside the Dev Container as `db:5432`

Recommended first-time Dev Container flow:
1. Create `.env` in the repository root with at least:
  ```env
  POSTGRES_USER=barista
  POSTGRES_PASSWORD=supersecret
  POSTGRES_DB=barista_db
  DATABASE_URL=postgresql://barista:supersecret@db:5432/barista_db
  GEMINI_API_KEY=your_gemini_api_key_here
  DISCORD_TOKEN=your_discord_bot_token_here
  ```
2. Run `Dev Containers: Reopen in Container`.
3. Wait for `postCreateCommand` to finish.
4. Verify the setup in the container terminal:
  - `python --version` (should show Python 3.14.3)
  - `python -m unittest discover -s tests -v`

Note: Keep your real API keys and Discord token in your local `.env` file. Secrets are not committed.

- Install dependencies: `pip install -r requirements.txt`
- Install pre-commit: `pip install pre-commit`
- Enable git hooks: `pre-commit install`
- Run all quality checks manually: `pre-commit run --all-files`
- Run syntax smoke check: `python -m compileall -q src`
- Run unit tests: `PYTHONPATH=src python -m unittest discover -s tests -v`
- Set Python path: `export PYTHONPATH=src:$PYTHONPATH` (or `set PYTHONPATH=src;%PYTHONPATH%` on Windows)
- Run Discord bot locally: `python src/core/discord_bot.py` (after setting up DB)
- Run MCP server: `python src/core/mcp_server.py`
- Test vision: `python src/core/main.py data/test_bag.jpg`
- Test vector search: `python src/ai/vector_search.py`
- Test scraping: `python src/scraping/scraper.py`
- View database: `python src/database/view_db.py`

## Public Release Checklist

Before marking the repository as public, verify the following:

- Secrets are not tracked (`.env` is ignored and only `config/.env.example` is committed).
- Quality checks pass locally: `pre-commit run --all-files`.
- Syntax check passes: `python -m compileall -q src`.
- Unit tests pass: `PYTHONPATH=src python -m unittest discover -s tests -v`.
- GitHub Actions CI is green on the latest commit.
- API keys and bot token in your personal `.env` are rotated if they were ever exposed.

## License

MIT License – feel free to modify and share!
