# Dr. Jean - Discord Bot

Dr. Jean is an advanced, multi-functional Discord bot powered by the Alien framework. It features AI-driven interactions via ATLAS, an emotional response system, Original Character (OC) creation and interaction, a suite of utility and administrative commands, and robust database integration for persisting user data and preferences.

## Features

*   **AI Interaction (ATLAS Engine via Alien Framework):**
    *   **General Q&A:** Ask ATLAS single-turn questions (`/atlas_ask`).
    *   **Contextual Chat:** Engage in multi-turn conversations (`/atlas_chat`, `/atlas_reset_session`, `/atlas_get_history`, `/atlas_list_sessions`).
    *   **Command Assistance:** Get suggestions for Alien framework commands (`/atlas_suggest_command`), generate shell commands (`/atlas_generate_command`), and scripts (`/atlas_generate_script`).
    *   **Pentesting Assistance (Simulated/Educational):** Leverage ATLAS for planning (`/atlas_plan`), generating detailed steps (`/atlas_generate_steps`), and summarizing tool outputs (`/atlas_summarize_output`).
    *   **Custom Mentions:** Send messages to users as Dr. Jean (`/jean_mention`).
*   **Emotional AI (Dr. Jean Persona):**
    *   Responds dynamically to mentions of "Dr. Jean" based on a calculated emotional rating.
    *   Manages user-specific emotional profiles, conversation topics, and interaction history.
    *   Special, configurable responses for designated "DAD_ID" and "DIRECTOR_ID" users, as well as "COUNSELOR_IDS" and "NICE_WHITELIST_IDS".
*   **Original Characters (OCs):**
    *   Users can create, update, list, and delete their own OCs (`/build_oc`, `/list_ocs`, `/delete_oc`).
    *   Interact with OCs, whose personalities and responses are powered by ATLAS (`/run_oc`).
*   **General Utilities & Tools:**
    *   **Birthday Management:** Add and store user birthdays (`$DrJean.tools.addBirthday`).
    *   **System/Network Tools (via WSL):** Execute commands like `nmap`, `whois`, `searchsploit`, `sherlock`, `msfvenom` (`/nmap`, `/whois`, etc.).
    *   **Encoding/Decoding:** Perform Base64, Hex, Caesar, ROT13, XOR, and Vigenere cipher operations (`/encode_base64`, `/decode_base64`, etc.).
    *   **Steganography:** Encode and decode messages using invisible ASCII characters (`/encode_invisible`, `/decode_invisible`).
    *   **Web Intelligence:** Build Google Dorks (`/build_dork`), spider URLs (`/spider`), and search Wikipedia (`/wiki_search`, `/wiki_pagedata`).
    *   **Cybersecurity Resources:** Find resources based on tags and keywords (`/resource`).
    *   **Idea Submission:** Allow users to submit ideas to "Jack" (`/tell_jack`).
    *   **User Preferences:** Users can set, get, list, and remove personal preferences for Dr. Jean (`/jean_prefs set`, `/jean_prefs get`, etc.).
*   **Administrative & Owner Commands:**
    *   **Bot Control:** Restart or shut down the bot (owner-only: `$DrJean.tools.restart`, `$DrJean.tools.kys`).
    *   **Slash Command Sync:** Synchronize application commands with Discord (owner-only: `$sync`).
    *   **Database Management (Owner-only):**
        *   List tables, view schemas (`$DrJean.sql.listTables`, `$DrJean.sql.getTableSchema`).
        *   Execute SELECT, UPDATE, DELETE queries directly (`$DrJean.sql.executeSelect`, etc.).
        *   Backup and flush data based on `backup_flag` (`$DrJean.sql.backup`, `$DrJean.sql.flush`).
    *   **Owner-Level Preference Management:** Manage preferences for any user (owner-only: `/owner_jean_prefs set_as_user`, etc.).
*   **Help System:**
    *   Comprehensive help for text-based commands (`$DrJean.tools.help`).
    *   Manual for all registered slash commands (`/manual`).
*   **Alien Framework Integration:**
    *   The bot leverages the custom `ALNv2017.py` (Alien) framework as its backend for many advanced functionalities.

## Setup and Installation

1.  **Clone the Repository:**
    ```bash
    git clone <repository_url>
    cd discordBot
    ```

2.  **Create a Virtual Environment (Recommended):**
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -U discord.py python-dotenv aiosqlite huggingface_hub requests beautifulsoup4 blessed
    ```
    *(Note: `huggingface_hub`, `requests`, `beautifulsoup4`, `blessed` are primarily dependencies for the Alien framework and its TUI/ATLAS features).*

4.  **Configuration:**
    *   Create a `.env` file in the root directory (`discordBot/`).
    *   Add the following required variables:
        ```env
        DISCORD_TOKEN=YOUR_DISCORD_BOT_TOKEN
        BOT_PREFIX=$
        ```
    *   Add any optional environment variables (see Configuration section below).

5.  **Database Setup:**
    *   Ensure the `database/schema.sql` file exists and defines the necessary table structures.
    *   On the first run, the bot will attempt to create a SQLite database file at `database/jean_bot.db` and execute the schema.

6.  **Run the Bot:**
    ```bash
    python bot.py
    ```

## Configuration

The bot uses a `.env` file for configuration.

### Required Environment Variables:

*   `DISCORD_TOKEN`: Your Discord bot token.
*   `BOT_PREFIX`: The prefix for text-based commands (e.g., `$` or `!`).

### Optional Environment Variables (for enhanced functionality):

*   `DAD_ID`: User ID for special "DAD" responses in `EmotionalCog` and witty mentions.
*   `DIRECTOR_ID`: User ID for special "DIRECTOR" responses in `EmotionalCog` and witty mentions.
*   `COUNSELOR_IDS`: Comma-separated list of user IDs for "counselor" witty mention responses.
*   `NICE_WHITELIST_IDS`: Comma-separated list of user IDs for "nice whitelist" witty mention responses.
*   `HF_TOKEN`: Hugging Face Hub token (if ATLAS uses it directly for model access).
*   `HF_CHAT_MODEL_ID`: Default Hugging Face model ID for chat (if ATLAS uses it directly).
    *   *Note: The primary LLM interaction seems to be configured for Ollama via the Alien framework.*

### Alien Framework Configuration:

Alien Repo: https://github.com/J4ck3LSyN-Gen2/Alien

The `ALNv2017.py` file contains an internal `self.configure` dictionary. Key settings to review and potentially update within `ALNv2017.py` include:
*   `ollama-configure`: Paths to the Ollama executable.
*   `atlas-configure`:
    *   `ollamaAPIURL`: The API endpoint for your Ollama instance (e.g., `http://localhost:11434/api/generate`).
    *   `defaultModelAsk`, `defaultModelCommandGen`, `defaultModelScriptGen`: Default Ollama models for different ATLAS tasks.
    *   `promptInjections`: Contains various system prompts for ATLAS, including PentestGPT-style prompts.
*   `shodan-configure`:
    *   `apiKey`: Your Shodan API key (set to `0` by default, needs to be updated for Shodan features).
*   `logPipe-configure`: Settings for Alien's internal logging.
*   Other module-specific configurations (e.g., `nmapPortScanner-configure`, `networkProxy-configure`).

## Usage

*   **Command Prefix:** Defined by `BOT_PREFIX` in your `.env` file (e.g., `$`). The bot also responds to mentions.
*   **Help:**
    *   For text-based commands: `$DrJean.tools.help`
    *   For slash commands: `/manual` for a list of all slash commands.
    *   For project overview: `/readme` to display this README file.
*   **Key Commands Examples:**
    *   `$DrJean.tools.kys` (Owner-only: Shuts down the bot)
    *   `$DrJean.tools.restart` (Owner-only: Restarts the bot)
    *   `$sync` (Owner-only: Syncs slash commands with Discord)
    *   `@DrJean hello` (Triggers witty mention response)
    *   `/atlas_ask What is the capital of France?`
    *   `/build_oc name="Shadow" persona_prompt="A mysterious rogue..."`
    *   `/run_oc name="Shadow" message="Greetings."`
    *   `$DrJean.tools.addBirthday @User 2000-01-01`
    *   `/tell_jack This is a great idea!`
    *   `/nmap arguments="-sV target.example.com"`

## Modules (Cogs)

The bot's functionality is organized into cogs:

*   **`general_cog.py`:**
    *   Handles a wide array of utility commands, including system tools (Nmap, Whois via WSL), encoding/decoding, Google Dorking, Wikipedia searches, idea submissions, user preferences, and general bot help commands.
    *   Manages several owner-only SQL database interaction commands.
*   **`emotional_cog.py`:**
    *   Implements the "Dr. Jean" emotional AI. It processes messages mentioning "Dr. Jean," manages user emotional profiles, conversation topics, and provides dynamic responses based on calculated emotional ratings.
    *   Includes special interaction logic for users defined by `DAD_ID` and `DIRECTOR_ID`.
*   **`oc_cog.py`:**
    *   Allows users to create, manage, and interact with Original Characters (OCs). OC responses are generated by the ATLAS AI engine.
*   **`owner_cog.py`:**
    *   Contains commands restricted to the bot owner, such as synchronizing slash commands (`$sync`) and managing user preferences for any user (`/owner_jean_prefs`).

## Alien Framework (`ALNv2017.py`)

This bot heavily integrates with the `ALNv2017.py` script, which is a part of the **Alien Framework**. The Alien Framework is a separate, comprehensive project providing a toolkit for:

*   **ATLAS Engine:** LLM interaction via Ollama (and potentially Hugging Face).
*   **System Command Execution:** Wrappers for tools like Nmap, Whois, etc.
*   **Data Manipulation:** Encoding, decoding, memory operations.
*   **Web Interaction:** Dorking, web scraping, Wikipedia API.
*   **Text User Interface (TUI):** An interactive terminal interface for Alien (the Discord bot serves as an alternative frontend).
*   **And various other utilities.**

The `ALNv2017.py` file included in this repository is a version of the Alien framework tailored or utilized by this bot. For full details on the Alien Framework itself, please refer to its own repository (if applicable).

The Alien instance is initialized within Dr. Jean and its modules are accessed to perform complex tasks.

## Error Handling
*   The bot includes error handlers for common command errors (e.g., cooldowns, missing permissions, command not found), providing feedback to the user.
*   Unhandled errors are logged to `discord.log` and raised to the console.
*   For issues or bug reports, please contact the bot owner/developer.
*   And various other utilities.

## Database (`database/schema.sql`)

The bot uses an SQLite database (`database/jean_bot.db`) to store persistent data. The schema is defined in `database/schema.sql` and includes the following tables:

*   **`jack_ideas`**: Stores ideas submitted by users via the `/tell_jack` command.
*   **`chat_sessions`**: Intended for storing LLM chat histories (primarily for direct Alien/ATLAS usage, not directly used by the Discord bot's current chat commands which manage context in-memory per session or via ATLAS's own context handling).
*   **`user_birthdays`**: Stores user IDs and their birthdays.
*   **`user_emotional_profiles`**: Tracks Dr. Jean's emotional rating towards users, interaction counts, current conversation topics, and user-defined preferences.
*   **`original_characters`**: Stores details of user-created OCs, including their name, creator, persona prompt for ATLAS, and interaction statistics.

All tables include a `backup_flag` column to control data inclusion in backups performed by the `$DrJean.sql.backup` command.

## Responses (`responses.json`)

The `responses.json` file contains lists of pre-defined witty or general responses for various mention scenarios (e.g., general mentions, mentions by DAD_ID, DIRECTOR_ID, etc.). The bot randomly selects from these lists when appropriate.

## Contributing

This project is currently maintained by a sole developer. Contributions are not actively sought at this time. For feature requests or bug reports, please contact the developer directly.

## License

Copyright © 2025 JackalSyn Ind.
Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the “Software”), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
