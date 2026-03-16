# BaristAI Discord Bot

An AI-powered Discord bot for coffee enthusiasts. Upload a photo of your coffee bag, and get personalized grind setting recommendations based on historical data from your brewing logs.

## Features

- **Image Analysis**: Uses Google Gemini Vision API to extract coffee details (roaster, origin, process, roast level) from bag photos.
- **RAG Recommendations**: Searches your PostgreSQL database for similar coffees and suggests optimal grind settings, dose, and brewing tips.
- **Feedback Loop**: React with 👍 to provide the actual grind setting you used (based on experience), which is saved back to the database for improved future recommendations.
- **Docker Ready**: Fully containerized for easy deployment on Linux servers.

## Prerequisites

- Python 3.11+
- Docker and Docker Compose
- A Discord account and server
- Google Gemini API key
- PostgreSQL (handled via Docker)

## Setup

### 1. Clone the Repository
```bash
git clone https://github.com/galdavido/BaristAI.git
cd BaristAI
```

### 2. Environment Configuration
Create a `.env` file in the root directory:
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

### 3. Build and Run with Docker
```bash
docker-compose up --build -d
```

This starts:
- PostgreSQL database on port 5434
- BaristAI bot (auto-initializes DB and seeds sample data)

### 4. Invite the Bot to Your Server
- In Discord Developer Portal > OAuth2 > URL Generator:
  - Scopes: `bot`
  - Permissions: Send Messages, Read Message History, Add Reactions
- Use the generated URL to invite the bot.

## Usage

1. **Upload an Image**: In a Discord channel, attach a photo of your coffee bag (JPG/PNG).
2. **Receive Analysis**: The bot replies with extracted coffee details and grind recommendations from your database.
3. **Provide Feedback**: If the suggestion is good, react with 👍. The bot saves this as a new log entry for future reference.

### Example Interaction
- User uploads `coffee_bag.jpg`
- Bot responds:
  ```
  ☕ **Blue Bottle Ethiopia Yirgacheffe**
  🌍 Ethiopia | Washed | Light

  💡 **Recommendation from database:**
  ☕ Similar coffee: Blue Bottle Ethiopia (Ethiopia, Washed)
     ⚙️ Grinder: Kingrinder K6
     🎯 Suggested setting: 39 clicks (16.0g dose)
     📝 Notes: Perfect balance...

  👍 React with thumbs up to save this setting!
  ```
- User reacts 👍
- Bot: "👍 Great! What was the actual grind setting you used? Reply e.g. '36 clicks' or 'fine'."
- User replies: "38 clicks"
- Bot: "✅ Saved: '38 clicks' setting to the database!"

## Equipment Setup

Before using the bot, set your espresso equipment so recommendations are tailored to your setup:

- `!set_grinder <brand> <model>` - Set your grinder (e.g., `!set_grinder Kingrinder K6`)
- `!set_machine <brand> <model>` - Set your espresso machine (e.g., `!set_machine AVX Hero Plus 2024`)
- `!show_equipment` - Display your current equipment settings

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

The scraper uses Google Gemini AI to extract structured data (brand, model, features) from product pages and stores them with vector embeddings for the RAG system.

## Code Comments and Architecture

### Key Files
- **`discord_bot.py`**: Main bot logic using `discord.py`. Handles events like `on_ready` and `on_message`. Processes attachments, calls vision/RAG modules, and manages reactions.
- **`vision.py`**: Uses Google GenAI to analyze images and extract structured coffee data via Pydantic schema.
- **`rag.py`**: Retrieval-Augmented Generation – queries the DB for similar coffees and formats recommendations.
- **`models.py`**: SQLAlchemy ORM models for `Bean`, `Equipment`, `DialInLog`.
- **`database.py`**: DB connection setup with SQLAlchemy.
- **`init_db.py` / `seed.py`**: Initialize tables and populate sample data.

### Bot Flow
1. **Message Received**: Check for image attachments.
2. **Vision Analysis**: Download image, send to Gemini, parse JSON response.
3. **DB Search**: Query for matching beans (by origin/process), retrieve logs with high ratings.
4. **Response**: Format and send recommendation.
5. **Feedback**: Wait for 👍 reaction, then save new log to DB.

### Notes
- The bot ignores its own messages to prevent loops.
- Temporary files are cleaned up after processing.
- DB operations use SQLAlchemy sessions for safety.
- Type checking is suppressed for `discord.py` (no stubs) using `# type: ignore`.

## Troubleshooting

- **Bot not responding?** Check logs: `docker-compose logs baristai-bot`. Ensure token is valid and intents enabled.
- **401 Unauthorized?** Reset Discord token and update `.env`.
- **No recommendations?** Seed data might be missing; run `python seed.py` locally or check DB.
- **Image analysis fails?** Verify Gemini API key and image quality.
- **Permissions issues?** Re-invite bot with correct permissions.

## Development

- Install dependencies: `pip install -r requirements.txt`
- Run locally: `python discord_bot.py` (after setting up DB)
- Test vision: `python main.py test_bag.jpg`

## License

MIT License – feel free to modify and share!
