import dotenv, os, json, sys, logging, asyncio, functools, random, re, datetime

### Discord Imports ###
import discord
from discord.ext import commands, tasks
import aiosqlite # Added for database
from discord.ext.commands import Context, Bot

from ALNv2017 import Alien # Import your Alien class

class LoggingFormatter(logging.Formatter):
    """*--Logging--*

    Stolen From https://github.com/kkrypt0nn/Python-Discord-Bot-Template
    """
    # Colors
    black = "\x1b[30m"
    red = "\x1b[31m"
    green = "\x1b[32m"
    yellow = "\x1b[33m"
    blue = "\x1b[34m"
    gray = "\x1b[38m"
    # Styles
    reset = "\x1b[0m"
    bold = "\x1b[1m"
    COLORS = {
        logging.DEBUG: gray + bold,
        logging.INFO: blue + bold,
        logging.WARNING: yellow + bold,
        logging.ERROR: red,
        logging.CRITICAL: red + bold,
    }

    def format(self, record):
        log_color = self.COLORS[record.levelno]
        format = "(black){asctime}(reset) (levelcolor){levelname:<8}(reset) (green){name}(reset) {message}"
        format = format.replace("(black)", self.black + self.bold)
        format = format.replace("(reset)", self.reset)
        format = format.replace("(levelcolor)", log_color)
        format = format.replace("(green)", self.green + self.bold)
        formatter = logging.Formatter(format, "%Y-%m-%d %H:%M:%S", style="{")
        return formatter.format(record)


logger = logging.getLogger("discord_bot")
logger.setLevel(logging.DEBUG)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(LoggingFormatter())
# File handler
file_handler = logging.FileHandler(filename="discord.log", encoding="utf-8", mode="w")
file_handler_formatter = logging.Formatter(
    "[{asctime}] [{levelname:<8}] {name}: {message}", "%Y-%m-%d %H:%M:%S", style="{"
)
file_handler.setFormatter(file_handler_formatter)

# Add the handlers
logger.addHandler(console_handler)
logger.addHandler(file_handler)

class jeanBot(commands.Bot):
    """*--Discord Bot Client--*
    """

    def __init__(self) -> None:
        """Initializes The Bot.
        """
        self.logger = logger # Assign logger early

        # Load responses from JSON
        self.friend_mention_responses = []
        self.director_mention_responses = []
        self.counselor_mention_responses = []
        self.nice_whitelist_mention_responses = []
        self.dad_mention_responses = []
        self.mention_responses = []
        self._load_responses_from_json()

        # Load DAD_ID for special interactions
        self.dad_id_str = os.getenv("DAD_ID")
        self.dad_id: int | None = None
        if self.dad_id_str:
            try:
                self.dad_id = int(self.dad_id_str)
                self.logger.info(f"DAD_ID loaded and parsed: {self.dad_id}")
            except ValueError:
                self.logger.warning(f"DAD_ID '{self.dad_id_str}' is not a valid integer. Dad-specific responses will not be used.")
        else:
            self.logger.info("DAD_ID not found in environment variables. No special 'dad' responses will be used.")

        self.messageMemory = {}
        self.listenChannels_ID = []
        self.listenChannels_STR = []
        self.blackListedCommands = {}
        self.alien_instance: Alien | None = None # To hold the Alien instance
        self.database = None # For aiosqlite connection
        self.whiteListedCommands = {}
        # For ATLAS queueing
        self.atlas_queue: asyncio.Queue | None = None
        self.atlas_processing_lock: asyncio.Lock | None = None

        # Helper function to parse comma-separated IDs
        def _parse_id_list(env_var_name: str) -> list[int]:
            ids_str = os.getenv(env_var_name)
            parsed_ids = []
            if ids_str:
                for id_val_str in ids_str.split(','):
                    try:
                        parsed_ids.append(int(id_val_str.strip()))
                    except ValueError:
                        self.logger.warning(f"Invalid ID '{id_val_str}' in {env_var_name}. Skipping.")
                self.logger.info(f"Loaded {len(parsed_ids)} IDs for {env_var_name}: {parsed_ids}")
            else:
                self.logger.info(f"{env_var_name} not found in environment variables. No special responses for this group.")
            return parsed_ids
        self.counselor_ids = _parse_id_list("COUNSELOR_IDS")
        self.nice_whitelist_ids = _parse_id_list("NICE_WHITELIST_IDS")        

        # Load DIRECTOR_ID
        self.director_id_str = os.getenv("DIRECTOR_ID")
        self.director_id: int | None = None
        if self.director_id_str:
            try:
                self.director_id = int(self.director_id_str)
                self.logger.info(f"DIRECTOR_ID loaded and parsed: {self.director_id}")
            except ValueError:
                self.logger.warning(f"DIRECTOR_ID '{self.director_id_str}' is not a valid integer. Director-specific responses will not be used.")
        else:
            self.logger.info("DIRECTOR_ID not found in environment variables. No special 'director' responses will be used.")

        self.mention_cooldown = commands.CooldownMapping.from_cooldown(1, 5.0, commands.BucketType.user) # 1 per 5s per user
        # Determine prefix consistently
        actual_prefix = os.getenv("BOT_PREFIX")
        if not actual_prefix:
            self.logger.warning(
                "BOT_PREFIX not found in environment variables or is empty. "
                "Using default prefix '$'."
            )
            actual_prefix = "$"
        self.bot_prefix = actual_prefix
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix=commands.when_mentioned_or(self.bot_prefix), # Use the consistently determined prefix
            intents=intents,
            help_command=None,
        )

        # Check if discord.py's automatic command registration (via BotMeta and __commands__) worked.
        class_commands_dict = getattr(self.__class__, '__commands__', None)
        if class_commands_dict is not None:
            self.logger.debug(f"After super().__init__: self.__class__.__commands__ (from BotMeta) contains: {[str(cmd_name) for cmd_name in class_commands_dict.keys()]}")
        else:
            self.logger.warning("After super().__init__: self.__class__.__commands__ attribute (from BotMeta) NOT FOUND. Manual command addition might be necessary for commands in this class.")

        # Commands defined directly in this class might still show the __commands__ warning.
        # Moving commands to Cogs is the recommended way to avoid these issues.

        self.logger.info(
            f"jeanBot initialized. Registered commands: {[str(cmd.name) for cmd in self.commands]}"
        )

    def _load_responses_from_json(self, filepath: str = "responses.json") -> None:
        """Loads response lists from a JSON file."""
        try:
            base_dir = os.path.realpath(os.path.dirname(__file__))
            full_path = os.path.join(base_dir, filepath)
            if not os.path.exists(full_path):
                self.logger.warning(f"Responses file '{full_path}' not found. Using empty lists for responses.")
                return

            with open(full_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            self.friend_mention_responses = data.get("friend_mention_responses", [])
            self.director_mention_responses = data.get("director_mention_responses", [])
            self.counselor_mention_responses = data.get("counselor_mention_responses", [])
            self.nice_whitelist_mention_responses = data.get("nice_whitelist_mention_responses", [])
            self.dad_mention_responses = data.get("dad_mention_responses", [])
            self.mention_responses = data.get("mention_responses", [])
            self.logger.info(f"Successfully loaded responses from '{full_path}'.")

        except (IOError, json.JSONDecodeError) as e:
            self.logger.error(f"Failed to load or parse responses from '{filepath}': {e}. Using empty lists.", exc_info=True)
        # The 'test' command will be registered when cogs are loaded via setup_hook.
        # A check for it here would be premature.

    async def setup_hook(self) -> None:
        """Called by discord.py after login but before connecting to Gateway."""
        await super().setup_hook() # Call parent's setup_hook for future-proofing
        self.logger.info(f"Logged in as {self.user.name} (ID: {self.user.id})")
        self.logger.info(f"discord.py API version: {discord.__version__}")
        self.logger.info("---")
        self.logger.info("Running setup_hook...")

        self.logger.info("Initializing ATLAS queue and lock...")
        self.atlas_queue = asyncio.Queue()
        self.atlas_processing_lock = asyncio.Lock()

        self.logger.info("Initializing Alien instance...")
        try:
            # noInit=1 might be useful if Alien's full init does too much for a bot environment
            self.alien_instance = Alien(noInit=1) 
            # Initialize ATLAS module and its dependencies
            if self.alien_instance:
                atlas_module = self.alien_instance.ATLAS # This will trigger lazy init of _ATLASModule
                atlas_module.initImports()      # Import requests, json, re for ATLAS
                atlas_module.loadPentestGPTPrompts() # Load specific prompts if needed by ATLAS functions
                self.logger.info("Alien instance and ATLAS module initialized.")
        except Exception as e:
            self.logger.critical(f"Failed to initialize Alien instance or ATLAS module: {e}", exc_info=True)
            # Depending on how critical Alien is, you might want to raise e or handle gracefully
        
        self.logger.info("Initializing database...")
        try:
            await self.init_db() # Sets self.db_path, prepares schema

            # Establish the persistent database connection
            # self.database is initialized to None in __init__
            # init_db does not set self.database to a connection object
            if not hasattr(self, 'db_path') or not self.db_path:
                # This should not happen if init_db succeeded without error,
                # as init_db is responsible for setting self.db_path or raising.
                self.logger.critical("CRITICAL: db_path not set after init_db call. Cannot proceed with database setup.")
                raise RuntimeError("Database path (self.db_path) was not set by init_db.")

            self.database = await aiosqlite.connect(self.db_path)
            self.logger.info(f"Persistent database connection established to: {self.db_path}")

        except Exception as e:
            # This catches exceptions from init_db() or aiosqlite.connect()
            self.logger.critical(f"Failed to initialize or connect to the database during setup_hook: {e}", exc_info=True)
            # Re-raise to stop bot execution if DB is essential.
            # Consider more graceful shutdown or feature degradation if appropriate for your bot.
            raise
            
        self.logger.info("Starting ATLAS worker task...")
        self.atlas_worker_task = asyncio.create_task(self.atlas_worker())
        self.logger.info("ATLAS worker task started.")

        self.logger.info(f"Checking discord.app_commands attributes before loading cogs. discord.py version: {discord.__version__}")
        try:
            # Ensure app_commands is imported if not already globally available in this scope in a way that dir() would see it.
            # discord.py typically makes it available via discord.app_commands
            self.logger.info(f"Attributes in discord.app_commands: {dir(discord.app_commands)}")
            if hasattr(discord.app_commands, 'is_owner'):
                self.logger.info("DIAGNOSTIC: discord.app_commands.is_owner IS FOUND.")
            else:
                self.logger.error("DIAGNOSTIC: discord.app_commands.is_owner IS NOT FOUND at this point.")
            
            # Further check within discord.app_commands.checks
            if hasattr(discord.app_commands, 'checks'):
                app_checks_module = discord.app_commands.checks
                self.logger.info(f"Attributes in discord.app_commands.checks: {dir(app_checks_module)}")
                if hasattr(app_checks_module, 'is_owner'):
                    self.logger.info("DIAGNOSTIC: discord.app_commands.checks.is_owner IS FOUND.")
                else:
                    self.logger.error("DIAGNOSTIC: discord.app_commands.checks.is_owner IS NOT FOUND.")
        except ImportError:
            self.logger.error("DIAGNOSTIC: Failed to import discord.app_commands for diagnostics.")
        except Exception as e_diag:
            self.logger.error(f"DIAGNOSTIC: Error during discord.app_commands diagnostics: {e_diag}")

        self.logger.info("Loading cogs...")
        await self.load_cogs()
        self.logger.info("Cogs loaded.")
        self.check_birthdays.start()

        # Start the terminal input loop task if it's an interactive session
        if sys.stdin.isatty():
            self.logger.info("Interactive terminal detected. Starting terminal input handler task...")
            self.terminal_task = asyncio.create_task(self.terminal_input_loop())
        else:
            self.logger.info("No interactive terminal (stdin is not a TTY). Terminal input handler will not be started.")
            self.terminal_task = None # Explicitly set to None

    @tasks.loop(time=datetime.time(hour=0, minute=5, tzinfo=datetime.timezone.utc)) # Run daily at 00:05 UTC
    async def check_birthdays(self):
        """Checks for user birthdays and logs them."""
        self.logger.info("Birthday Check: Task started.")
        if not self.database:
            self.logger.error("Birthday Check: Database connection is not available.")
            return
        today = datetime.date.today()
        self.logger.info(f"Birthday Check: Today is {today.strftime('%Y-%m-%d')}. Checking for birthdays.")

        try:
            async with self.database.execute("SELECT user_id, birthday FROM user_birthdays") as cursor:
                birthdays_today = []
                async for row in cursor:
                    user_id, birthday_str = row
                    try:
                        # Birthdays are stored as 'YYYY-MM-DD'
                        birth_date = datetime.datetime.strptime(birthday_str, "%Y-%m-%d").date()
                        if birth_date.month == today.month and birth_date.day == today.day:
                            birthdays_today.append(user_id)
                            self.logger.info(f"Birthday Check: It's user ID {user_id}'s birthday today ({birthday_str})!")
                            # Placeholder for future actions:
                            try:
                                user = await self.fetch_user(user_id)
                                general_channel = self.get_channel(722687810070380647)
                                if general_channel and user:
                                    await general_channel.send(f"Happy Birthday {user.mention}!")
                            except discord.NotFound:
                                self.logger.warning(f"Birthday Check: Could not find user with ID {user_id} to wish happy birthday.")
                            except Exception as e_user:
                                self.logger.error(f"Birthday Check: Error fetching user {user_id} or sending message: {e_user}")

                    except ValueError:
                        self.logger.error(f"Birthday Check: Could not parse birthday string '{birthday_str}' for user ID {user_id}.")
                if not birthdays_today:
                    self.logger.info("Birthday Check: No birthdays today.")
        except Exception as e:
            self.logger.error(f"Birthday Check: An error occurred while checking birthdays: {e}", exc_info=True)
        self.logger.info("Birthday Check: Task finished.")


    async def atlas_worker(self):
        """Processes ATLAS requests from the queue one at a time."""
        self.logger.info("ATLAS worker started and waiting for requests.")
        if not self.atlas_queue or not self.atlas_processing_lock or not self.alien_instance:
            self.logger.critical("ATLAS worker cannot start: queue, lock, or Alien instance not initialized.")
            return

        while True:
            try:
                request_item = await self.atlas_queue.get()
                self.logger.info(f"ATLAS worker picked up request for: {request_item['method_name']}")

                method_name = request_item["method_name"]
                args = request_item["args"]
                kwargs = request_item["kwargs"]
                future = request_item["future"]

                async with self.atlas_processing_lock: # Ensure only one task processes at a time
                    self.logger.info(f"ATLAS worker processing: {method_name} with lock acquired.")
                    try:
                        atlas_module = self.alien_instance.ATLAS
                        if not hasattr(atlas_module, method_name):
                            raise AttributeError(f"ATLAS module does not have method '{method_name}'.")
                        
                        method_to_call = getattr(atlas_module, method_name)
                        
                        # Use functools.partial for cleaner passing of args/kwargs to to_thread
                        # This is the synchronous, potentially long-running part
                        func_with_args = functools.partial(method_to_call, *args, **kwargs)
                        result = await asyncio.to_thread(func_with_args)
                        
                        future.set_result(result)
                        self.logger.info(f"ATLAS worker successfully processed: {method_name}")
                    except Exception as e:
                        self.logger.error(f"ATLAS worker error processing {method_name}: {e}", exc_info=True)
                        future.set_exception(e)
                
                self.atlas_queue.task_done()
            except asyncio.CancelledError:
                self.logger.info("ATLAS worker task cancelled.")
                break
            except Exception as e: # Catch-all for unexpected errors in the worker loop itself
                self.logger.critical(f"Critical error in ATLAS worker loop: {e}", exc_info=True)
                await asyncio.sleep(5) # Avoid fast error loops

    async def load_cogs(self) -> None:
        """
        The code in this function is executed whenever the bot will start.
        """
        for file in os.listdir(f"{os.path.realpath(os.path.dirname(__file__))}/cogs"):
            if file.endswith(".py"):
                extension = file[:-3]
                try:
                    await self.load_extension(f"cogs.{extension}")
                    self.logger.info(f"Loaded extension '{extension}'")
                except Exception as e:
                    exception = f"{type(e).__name__}: {e}"
                    self.logger.error(
                        f"Failed to load extension {extension}\n{exception}"
                    )

    # This is the primary init_db method now.
    async def init_db(self) -> None:
        """
        Initializes the database file, path, and executes the schema.
        This method sets `self.db_path` and ensures the database file
        and schema are set up. The persistent connection to `self.database`
        is established later in `setup_hook`.
        If this method fails, it will raise an exception, which should
        be handled by the caller (e.g., `setup_hook`) to prevent the bot
        from starting in an inconsistent state.
        """
        try:
            base_dir = os.path.realpath(os.path.dirname(__file__))
            db_folder_path = os.path.join(base_dir, "database")

            if not os.path.exists(db_folder_path):
                os.makedirs(db_folder_path)
                self.logger.info(f"Created database directory: {db_folder_path}")

            self.db_path = os.path.join(db_folder_path, "jean_bot.db")
            self.logger.info(f"Database path set to: {self.db_path}")

            # Connect temporarily to initialize schema
            async with aiosqlite.connect(self.db_path) as db:
                schema_file_path = os.path.join(db_folder_path, "schema.sql")
                if os.path.exists(schema_file_path):
                    self.logger.info(f"Found schema file: {schema_file_path}. Attempting to execute.")
                    with open(schema_file_path, "r", encoding="utf-8") as f:
                        script_content = f.read()
                    if script_content.strip(): # Ensure script is not empty
                        await db.executescript(script_content)
                        await db.commit()
                        self.logger.info(f"Database schema from '{schema_file_path}' executed successfully.")
                    else:
                        self.logger.warning(f"Schema file '{schema_file_path}' is empty. No schema executed.")
                else:
                    self.logger.warning(
                        f"Schema file 'database/schema.sql' not found at '{schema_file_path}'. "
                        f"Database at '{self.db_path}' will be opened without schema execution. "
                        "It might be empty or rely on an existing schema."
                    )
        except OSError as e: # For os.makedirs
            self.logger.critical(f"Failed to create database directory '{db_folder_path}': {e}", exc_info=True)
            raise  # Re-raise to be caught by setup_hook
        except aiosqlite.Error as e:
            self.logger.error(f"An error occurred during database schema initialization for '{self.db_path}': {e}", exc_info=True)
            raise # Re-raise to be caught by setup_hook
        except Exception as e: # Catch any other unexpected error
            self.logger.critical(f"An unexpected error occurred during init_db: {e}", exc_info=True)
            raise # Re-raise to be caught by setup_hook

    async def terminal_input_loop(self):
        """Handles input from the terminal to send messages as the bot."""
        self.logger.info("Terminal input handler started. Type 'helpcli' for commands or 'exitcli' to stop this handler.")
        while True:
            try:
                # Run input() in a separate thread to avoid blocking asyncio loop
                command_line = await asyncio.to_thread(input, "BotCLI> ")
                if not command_line.strip():
                    continue

                parts = command_line.strip().split(" ", 2)
                command = parts[0].lower()

                if command == "exitcli":
                    self.logger.info("Terminal input: 'exitcli' received. Stopping terminal input handler.")
                    break
                elif command == "helpcli":
                    print("\nAvailable BotCLI commands:")
                    print("  send <channel_id> <message>   - Send a message to a specific channel.")
                    print("  dm <user_id_or_name#disc> <message> - Send a direct message to a specific user.")
                    print("  listguilds                    - Lists all guilds the bot is in.")
                    print("  listchannels <guild_id>       - Lists all channels in a specific guild.")
                    print("  listusers <guild_id>          - Lists all users in a specific guild.")
                    print("  exitcli                       - Stop this terminal input handler (bot continues running).\n")                    

                elif command == "send":
                    if len(parts) < 3:
                        print("Usage: send <channel_id> <message_content>")
                        self.logger.warning("BotCLI: 'send' command with insufficient arguments.")
                        continue
                    
                    channel_id_str = parts[1]
                    message_content = parts[2]                    
                    target_channel = None

                    try:
                        # Try to interpret as channel ID first
                        channel_id = int(channel_id_str)
                        target_channel = self.get_channel(channel_id)
                        if target_channel:
                            self.logger.info(f"BotCLI: Identified channel by ID: {channel_id}")
                    except ValueError:
                        # Not an ID, try to find by name
                        self.logger.info(f"BotCLI: Channel identifier '{channel_id_str}' is not an ID, searching by name.")
                        found_channels = []
                        for guild in self.guilds:
                            for channel_in_guild in guild.text_channels: # Only text channels
                                if channel_in_guild.name.lower() == channel_id_str.lower():
                                    found_channels.append(channel_in_guild)
                        
                        if len(found_channels) == 1:
                            target_channel = found_channels[0]
                            self.logger.info(f"BotCLI: Found channel '{target_channel.name}' (ID: {target_channel.id}) in guild '{target_channel.guild.name}'.")
                        elif len(found_channels) > 1:
                            print(f"BotCLI Warning: Multiple channels found with name '{channel_id_str}'. Using the first one found: '{found_channels[0].name}' in guild '{found_channels[0].guild.name}'.")
                            print("Consider using Channel ID for precision.")
                            self.logger.warning(f"BotCLI: Multiple channels found for name '{channel_id_str}'. Used first: {found_channels[0].id} in {found_channels[0].guild.id}")
                            target_channel = found_channels[0]
                        # If no channels found by name, target_channel remains None

                    if target_channel:
                        try:
                            await target_channel.send(message_content)
                            self.logger.info(f"BotCLI: Sent message to channel {target_channel.id}: '{message_content}'")
                            print(f"Message sent to channel {target_channel.name} (ID: {target_channel.id}).")
                        except discord.Forbidden:
                            print(f"BotCLI Error: Bot does not have permission to send messages to channel {target_channel.id}.")
                            self.logger.error(f"BotCLI: Permission denied for sending to channel {target_channel.id}.")
                        except discord.HTTPException as e:
                            print(f"BotCLI Error: Failed to send message to channel {target_channel.id}: {e}")
                            self.logger.error(f"BotCLI: HTTPException sending to channel {target_channel.id}: {e}")
                        except Exception as e:
                            print(f"BotCLI Error: An unexpected error occurred while sending message: {e}")
                            self.logger.error(f"BotCLI: Unexpected error sending to channel {target_channel.id}: {e}", exc_info=True)
                    else:
                        print(f"BotCLI Error: Channel with identifier '{channel_id_str}' not found or not accessible by the bot.")
                        self.logger.warning(f"BotCLI: Channel '{channel_id_str}' not found.")

                elif command == "dm":
                    if len(parts) < 3:
                        print("Usage: dm <user_id_or_name#discriminator> <message_content>")
                        self.logger.warning("BotCLI: 'dm' command with insufficient arguments.")
                        continue

                    user_identifier = parts[1]
                    message_content = parts[2]
                    target_user: discord.User | discord.Member | None = None

                    try:
                        # Try to interpret as user ID first
                        user_id = int(user_identifier)
                        target_user = self.get_user(user_id)
                        if not target_user: # If not in cache, try fetching
                             target_user = await self.fetch_user(user_id)
                        if target_user:
                            self.logger.info(f"BotCLI: Identified user by ID: {user_id}")
                    except ValueError:
                        # Not an ID, try to find by name#discriminator or name
                        self.logger.info(f"BotCLI: User identifier '{user_identifier}' is not an ID, searching by name.")
                        found_user_by_name = None
                        if '#' in user_identifier:
                            try:
                                name_part, discrim_part = user_identifier.rsplit('#', 1)
                                found_user_by_name = discord.utils.get(self.users, name=name_part, discriminator=discrim_part)
                            except ValueError: # rsplit failed or discrim_part not valid
                                pass 
                        if not found_user_by_name: # Try plain name if not found by name#disc or if no # was present
                            found_user_by_name = discord.utils.get(self.users, name=user_identifier)
                        
                        if found_user_by_name:
                            target_user = found_user_by_name
                            self.logger.info(f"BotCLI: Found user by name (global cache): {target_user.name}#{target_user.discriminator} (ID: {target_user.id})")
                        else:
                            # More exhaustive search through guilds if still not found
                            for guild in self.guilds:
                                member = guild.get_member_named(user_identifier)
                                if member:
                                    target_user = member
                                    self.logger.info(f"BotCLI: Found member in guild '{guild.name}': {target_user.name}#{target_user.discriminator} (ID: {target_user.id})")
                                    break # Found one
                            if not target_user:
                                print(f"BotCLI Warning: Could not find user by name '{user_identifier}'. Using User ID is more reliable.")
                                self.logger.warning(f"BotCLI: User '{user_identifier}' not found by name search.")
                    except discord.NotFound:
                        print(f"BotCLI Error: User with ID {user_identifier} not found (discord.NotFound).")
                        self.logger.warning(f"BotCLI: User ID {user_identifier} not found via fetch_user.")
                    except Exception as e: # Catch other errors during user fetching
                        print(f"BotCLI Error: An error occurred while trying to find user '{user_identifier}': {e}")
                        self.logger.error(f"BotCLI: Error fetching user '{user_identifier}': {e}", exc_info=True)

                    if target_user:
                        try:
                            await target_user.send(message_content)
                            self.logger.info(f"BotCLI: Sent DM to user {target_user.id}: '{message_content}'")
                            print(f"DM sent to {target_user.name}#{target_user.discriminator} (ID: {target_user.id}).")
                        except discord.Forbidden:
                            print(f"BotCLI Error: Bot cannot send DMs to user {target_user.id} (e.g., user has DMs disabled or bot is blocked).")
                            self.logger.error(f"BotCLI: Permission denied for sending DM to user {target_user.id}.")
                        except discord.HTTPException as e:
                            print(f"BotCLI Error: Failed to send DM to user {target_user.id}: {e}")
                            self.logger.error(f"BotCLI: HTTPException sending DM to user {target_user.id}: {e}")
                        except Exception as e:
                            print(f"BotCLI Error: An unexpected error occurred while sending DM: {e}")
                            self.logger.error(f"BotCLI: Unexpected error sending DM to user {target_user.id}: {e}", exc_info=True)
                    else:
                        # This 'else' is hit if target_user remained None after all attempts
                        # and it wasn't an ID that failed with discord.NotFound (already handled)
                        if not user_identifier.isdigit(): # Only print if it wasn't an ID that failed
                            print(f"BotCLI Error: User with identifier '{user_identifier}' not found.")

                elif command == "listguilds":
                    if not self.guilds:
                        print("Bot is not currently in any guilds.")
                        self.logger.info("BotCLI: listguilds - Bot is not in any guilds.")
                    else:
                        print("\nGuilds the bot is in:")
                        for guild in self.guilds:
                            print(f"  - ID: {guild.id}, Name: {guild.name}")
                        print("")
                        self.logger.info(f"BotCLI: Listed {len(self.guilds)} guilds.")

                elif command == "listchannels":
                    if len(parts) < 2:
                        print("Usage: listchannels <guild_id>")
                        self.logger.warning("BotCLI: 'listchannels' command with insufficient arguments.")
                        continue
                    try:
                        guild_id = int(parts[1])
                        guild = self.get_guild(guild_id)
                        if guild:
                            print(f"\nChannels in guild '{guild.name}' (ID: {guild.id}):")
                            if not guild.channels:
                                print("  No channels found in this guild.")
                            for channel in sorted(guild.channels, key=lambda c: c.position): # Sort by position
                                print(f"  - ID: {channel.id}, Name: {channel.name}, Type: {channel.type}")
                            print("")
                            self.logger.info(f"BotCLI: Listed channels for guild {guild_id}.")
                        else:
                            print(f"BotCLI Error: Guild with ID {guild_id} not found.")
                            self.logger.warning(f"BotCLI: Guild {guild_id} not found for listchannels.")
                    except ValueError:
                        print(f"BotCLI Error: Invalid guild ID '{parts[1]}'. Must be a number.")
                        self.logger.warning(f"BotCLI: Invalid guild ID format '{parts[1]}' for listchannels.")

                elif command == "listusers":
                    if len(parts) < 2:
                        print("Usage: listusers <guild_id>")
                        self.logger.warning("BotCLI: 'listusers' command with insufficient arguments.")
                        continue
                    try:
                        guild_id = int(parts[1])
                        guild = self.get_guild(guild_id)
                        if guild:
                            print(f"\nUsers in guild '{guild.name}' (ID: {guild.id}):")
                            if not guild.members: # Should always have at least the bot
                                print("  No users found in this guild (this is unexpected).")
                            for member in guild.members:
                                print(f"  - ID: {member.id}, Name: {member.name}#{member.discriminator} (Nick: {member.nick})")
                            print("")
                            self.logger.info(f"BotCLI: Listed users for guild {guild_id}.")
                        else:
                            print(f"BotCLI Error: Guild with ID {guild_id} not found.")
                            self.logger.warning(f"BotCLI: Guild {guild_id} not found for listusers.")
                    except ValueError:
                        print(f"BotCLI Error: Invalid guild ID '{parts[1]}'. Must be a number.")
                        self.logger.warning(f"BotCLI: Invalid guild ID format '{parts[1]}' for listusers.")
                else:
                    print(f"BotCLI: Unknown command '{command}'. Type 'helpcli' for available commands.")
                    self.logger.warning(f"BotCLI: Unknown command '{command}'.")
            except (EOFError, KeyboardInterrupt): # Handle Ctrl+D or Ctrl+C in terminal for this loop
                self.logger.info("Terminal input: EOF or KeyboardInterrupt received. Stopping terminal input handler.")
                break
            except Exception as e:
                self.logger.error(f"Error in terminal input loop: {e}", exc_info=True)
                print(f"An error occurred in the terminal input handler: {e}")
                await asyncio.sleep(1) # Avoid fast error loops

    ### Internals ###

    async def on_ready(self) -> None:
        """On Ready Event.
        """
        self.logger.info(f'{self.user} has connected to Discord!')

    async def on_message(self, message:discord.Message) -> None:
        """Message Handler.
        """
        if message.author == self.user or message.author.bot:
            return

        # Log received messages using the bot's logger
        guild_name = message.guild.name if message.guild else "DM"
        channel_name = getattr(message.channel, 'name', f"ID:{message.channel.id}")
        self.logger.info(
            f"Msg from {message.author} (ID:{message.author.id}) in #{channel_name} (ID:{message.channel.id}) "
            f"of Guild: {guild_name} (ID:{message.guild.id if message.guild else 'N/A'}): {message.content}"
        )

        # Witty response for mentions (casual or failed command attempts)
        if self.user in message.mentions:
            # Determine if the mention is being used as a command prefix
            # These include the trailing space, e.g., "<@USER_ID> "
            mention_command_prefixes = [f'<@{self.user.id}> ', f'<@!{self.user.id}> ']
            
            is_potential_command_via_mention = False
            for m_prefix in mention_command_prefixes:
                if message.content.strip().startswith(m_prefix):
                    is_potential_command_via_mention = True
                    break
            
            if not is_potential_command_via_mention:
                self.logger.info(f"Bot mentioned by {message.author.id}, not as a command prefix. Message: '{message.content}'.")

            # Determine if EmotionalCog should handle this due to "Dr.Jean"
            # Condition 1: "dr.jean" is in the raw message content
            text_contains_dr_jean = re.search(r"dr\.jean", message.content, re.IGNORECASE) is not None

            # Condition 2: Bot is mentioned AND its display name is "Dr.Jean"
            bot_is_mentioned_and_is_drjean = False
            if message.guild: # Nicknames are per-guild
                guild_member_bot = message.guild.get_member(self.user.id)
                bot_display_name = guild_member_bot.nick if guild_member_bot and guild_member_bot.nick else self.user.name
            else: # DM context
                bot_display_name = self.user.name
            
            if re.search(r"dr\.jean", bot_display_name, re.IGNORECASE):
                # Check if the mention was specifically to the bot
                if message.content.startswith(f"<@{self.user.id}>") or \
                   message.content.startswith(f"<@!{self.user.id}>"):
                    bot_is_mentioned_and_is_drjean = True

            let_emotional_cog_handle = text_contains_dr_jean or bot_is_mentioned_and_is_drjean

            if not is_potential_command_via_mention and not let_emotional_cog_handle:
                # This is a casual mention, and EmotionalCog is not expected to handle it.
                bucket = self.mention_cooldown.get_bucket(message)
                retry_after = bucket.update_rate_limit() # type: ignore
                if not retry_after:
                    response_list_to_use = self.mention_responses
                    # Priority: Dad > Director > Counselors > Nice Whitelist > General
                    if self.dad_id and message.author.id == self.dad_id:
                        response_list_to_use = self.dad_mention_responses if self.dad_mention_responses else self.mention_responses
                    elif self.director_id and message.author.id == self.director_id:
                        self.logger.info(f"Director (ID: {message.author.id}) casually mentioned the bot. Using director-specific responses.")
                        response_list_to_use = self.director_mention_responses if self.director_mention_responses else self.mention_responses
                    elif self.counselor_ids and message.author.id in self.counselor_ids:
                        self.logger.info(f"Counselor (ID: {message.author.id}) casually mentioned the bot. Using counselor-specific responses.")
                        response_list_to_use = self.counselor_mention_responses if self.counselor_mention_responses else self.mention_responses
                    elif self.nice_whitelist_ids and message.author.id in self.nice_whitelist_ids:
                        self.logger.info(f"Nice Whitelist user (ID: {message.author.id}) casually mentioned the bot. Using nice_whitelist-specific responses.")
                        response_list_to_use = self.nice_whitelist_mention_responses if self.nice_whitelist_mention_responses else self.mention_responses
                    response = random.choice(response_list_to_use)
                    try:
                        await message.channel.send(response)
                    except discord.Forbidden:
                        self.logger.warning(f"Cannot send casual mention response to {message.channel.id} in {message.guild.id if message.guild else 'DM'}: Missing permissions.")
                    except discord.HTTPException as e:
                        self.logger.error(f"Failed to send casual mention response: {e}")
                else:
                    self.logger.info(f"Casual mention response for {message.author.id} on cooldown for {retry_after:.2f}s.")
            elif let_emotional_cog_handle: # This covers cases where "Dr.Jean" is in content or bot is mentioned as Dr.Jean
                self.logger.info(f"Bot mentioned. Message involves 'Dr.Jean' (in content or by mention name/nickname). EmotionalCog should handle. Skipping witty response in jeanBot.on_message.")

        await self.process_commands(message)

    ### Errors ###
    async def on_command_error(self, context: Context, error) -> None:
        """
        The code in this event is executed every time a normal valid command catches an error.

        :param context: The context of the normal command that failed executing.
        :param error: The error that has been faced.
        """
        if isinstance(error, commands.CommandOnCooldown):
            minutes, seconds = divmod(error.retry_after, 60)
            hours, minutes = divmod(minutes, 60)
            hours = hours % 24
            embed = discord.Embed(
                description=f"**Please slow down** - You can use this command again in {f'{round(hours)} hours' if round(hours) > 0 else ''} {f'{round(minutes)} minutes' if round(minutes) > 0 else ''} {f'{round(seconds)} seconds' if round(seconds) > 0 else ''}.",
                color=0xE02B2B,
            )
            await context.send(embed=embed)
        elif isinstance(error, commands.NotOwner):
            embed = discord.Embed(
                description="You are not the owner of the bot!", color=0xE02B2B
            )
            await context.send(embed=embed)
            if context.guild:
                self.logger.warning(
                    f"{context.author} (ID: {context.author.id}) tried to execute an owner only command in the guild {context.guild.name} (ID: {context.guild.id}), but the user is not an owner of the bot."
                )
            else:
                self.logger.warning(
                    f"{context.author} (ID: {context.author.id}) tried to execute an owner only command in the bot's DMs, but the user is not an owner of the bot."
                )
        elif isinstance(error, commands.MissingPermissions):
            embed = discord.Embed(
                description="You are missing the permission(s) `"
                + ", ".join(error.missing_permissions)
                + "` to execute this command!",
                color=0xE02B2B,
            )
            await context.send(embed=embed)
        elif isinstance(error, commands.BotMissingPermissions):
            embed = discord.Embed(
                description="I am missing the permission(s) `"
                + ", ".join(error.missing_permissions)
                + "` to fully perform this command!",
                color=0xE02B2B,
            )
            await context.send(embed=embed)
        elif isinstance(error, commands.MissingRequiredArgument):
            embed = discord.Embed(
                title="Error!",
                # We need to capitalize because the command arguments have no capital letter in the code and they are the first word in the error message.
                description=str(error).capitalize(),
                color=0xE02B2B,
            )
            await context.send(embed=embed)
        elif isinstance(error, commands.CommandNotFound):
            # Check if the prefix used was one of the bot's mentions
            # context.bot refers to the bot instance (self)
            possible_mention_prefixes = [
                f'<@{context.bot.user.id}> ',  # e.g. <@123456789> 
                f'<@!{context.bot.user.id}> '   # e.g. <@!123456789> (nickname mention)
            ]
            if context.prefix in possible_mention_prefixes:
                # It was a CommandNotFound triggered by a mention prefix.
                # This includes standalone mentions like "@BotName" or "@BotName unknown_command".
                self.logger.info(
                    f"CommandNotFound for mention prefix: '{context.message.content}'. "
                    f"Invoked by: {context.author} (ID: {context.author.id}). "
                    f"Attempted command name: '{context.invoked_with}'. "
                    "Checking if EmotionalCog should handle or if witty response is appropriate."
                )
                # Check if EmotionalCog should handle this (similar logic to on_message)
                text_contains_dr_jean_ctx = re.search(r"dr\.jean", context.message.content, re.IGNORECASE) is not None
                bot_is_mentioned_and_is_drjean_ctx = False
                if context.guild:
                    guild_member_bot_ctx = context.guild.get_member(self.user.id)
                    bot_display_name_ctx = guild_member_bot_ctx.nick if guild_member_bot_ctx and guild_member_bot_ctx.nick else self.user.name
                else:
                    bot_display_name_ctx = self.user.name
                if re.search(r"dr\.jean", bot_display_name_ctx, re.IGNORECASE):
                    if context.message.content.startswith(f"<@{self.user.id}>") or \
                       context.message.content.startswith(f"<@!{self.user.id}>"):
                        bot_is_mentioned_and_is_drjean_ctx = True
                
                let_emotional_cog_handle_ctx = text_contains_dr_jean_ctx or bot_is_mentioned_and_is_drjean_ctx

                if not let_emotional_cog_handle_ctx:
                    bucket = context.bot.mention_cooldown.get_bucket(context.message)
                    retry_after = bucket.update_rate_limit() # type: ignore
                    if not retry_after:
                        response_list_to_use = context.bot.mention_responses
                        # Priority: Dad > Director > Counselors > Nice Whitelist > General
                        if context.bot.dad_id and context.author.id == context.bot.dad_id:
                            response_list_to_use = context.bot.dad_mention_responses if context.bot.dad_mention_responses else context.bot.mention_responses
                        elif context.bot.director_id and context.author.id == context.bot.director_id:
                            context.bot.logger.info(f"Director (ID: {context.author.id}) triggered CommandNotFound via mention. Using director-specific responses.")
                            response_list_to_use = context.bot.director_mention_responses if context.bot.director_mention_responses else context.bot.mention_responses
                        elif context.bot.counselor_ids and context.author.id in context.bot.counselor_ids:
                            context.bot.logger.info(f"Counselor (ID: {context.author.id}) triggered CommandNotFound via mention. Using counselor-specific responses.")
                            response_list_to_use = context.bot.counselor_mention_responses if context.bot.counselor_mention_responses else context.bot.mention_responses
                        elif context.bot.nice_whitelist_ids and context.author.id in context.bot.nice_whitelist_ids:
                            context.bot.logger.info(f"Nice Whitelist user (ID: {context.author.id}) triggered CommandNotFound via mention. Using nice_whitelist-specific responses.")
                            response_list_to_use = context.bot.nice_whitelist_mention_responses if context.bot.nice_whitelist_mention_responses else context.bot.mention_responses
                        response = random.choice(response_list_to_use)
                        try:
                            await context.send(response) # Send in the same context
                        except discord.Forbidden:
                            context.bot.logger.warning(f"Cannot send witty response (from CommandNotFound) to {context.channel.id}: Missing permissions.")
                        except discord.HTTPException as e_http:
                            context.bot.logger.error(f"Failed to send witty response (from CommandNotFound): {e_http}")
                    else:
                        context.bot.logger.info(f"Witty response (from CommandNotFound) for {context.author.id} on cooldown for {retry_after:.2f}s.")
                else:
                    self.logger.info(f"CommandNotFound for mention prefix, but interaction involves 'Dr.Jean'. EmotionalCog should handle. Skipping witty response in on_command_error.")
            else:
                # Original CommandNotFound logging for non-mention prefixes
                self.logger.warning(
                    f"CommandNotFound error: '{error}'. Invoked by: {context.author} (ID: {context.author.id}). Message: '{context.message.content}'. Command: '{context.invoked_with}'. Prefix: '{context.prefix}'."
                )
        else:
            raise error        

    async def close(self):
        """Custom close method to gracefully shut down tasks and resources."""
        self.logger.info("Custom close method: Shutting down bot...")
        
        # Cancel the terminal input task
        if hasattr(self, 'terminal_task') and self.terminal_task and not self.terminal_task.done():
            self.logger.info("Cancelling terminal input task...")
            self.terminal_task.cancel()
            try:
                await self.terminal_task # Wait for the task to acknowledge cancellation
            except asyncio.CancelledError:
                self.logger.info("Terminal input task successfully cancelled.")
            except Exception as e:
                self.logger.error(f"Error encountered while awaiting terminal task cancellation: {e}", exc_info=True)
        
        # Cancel the ATLAS worker task
        if hasattr(self, 'atlas_worker_task') and self.atlas_worker_task and not self.atlas_worker_task.done():
            self.logger.info("Cancelling ATLAS worker task...")
            self.atlas_worker_task.cancel()
            try:
                await self.atlas_worker_task
            except asyncio.CancelledError:
                self.logger.info("ATLAS worker task successfully cancelled.")
            except Exception as e:
                self.logger.error(f"Error during ATLAS worker task cancellation: {e}", exc_info=True)

        # Close the database connection
        if self.database: # self.database is the aiosqlite.Connection object
            self.logger.info("Closing database connection from bot.close()...")
            await self.database.close()
            self.logger.info("Database connection closed.")
        else:
            self.logger.info("No active database connection to close in bot.close().")

        await super().close() # Important to call the parent's close method
        self.logger.info("Bot has been fully closed.")

### Program Start ###

'''
Default Intents.

intents.bans = True
intents.dm_messages = True
intents.dm_reactions = True
intents.dm_typing = True
intents.emojis = True
intents.emojis_and_stickers = True
intents.guild_messages = True
intents.guild_reactions = True
intents.guild_scheduled_events = True
intents.guild_typing = True
intents.guilds = True
intents.integrations = True
intents.invites = True
intents.messages = True # `message_content` is required to get the content of the messages
intents.reactions = True
intents.typing = True
intents.voice_states = True
intents.webhooks = True

Privileged Intents (Needs to be enabled on developer portal of Discord), please use them only if you need them:
intents.members = True
intents.message_content = True
intents.presences = True
'''
def Initialize():
    dotenv.load_dotenv() # Load .env variables first

    # Check for essential environment variables
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        logger.critical("DISCORD_TOKEN environment variable not found. The bot cannot start.")
        sys.exit("FATAL: DISCORD_TOKEN is not set. Please check your .env file or environment variables.")

    hf_token = os.getenv('HF_TOKEN')
    hf_model = os.getenv('HF_CHAT_MODEL_ID')

    if not hf_token:
        logger.warning("HF_TOKEN environment variable not found. LLM features may not work.")
    if not hf_model:
        logger.warning("HF_CHAT_MODEL_ID environment variable not found. LLM features may not work with a default or fail.")

    # BOT_PREFIX is now handled by jeanBot's __init__, including logging for defaults.
    
    client = jeanBot()
    try:
        client.run(token)
    except Exception as e:
        logger.critical(f"Bot failed to run: {e}", exc_info=True)
    finally:
        # Ensure the database connection is closed if the bot loop ends
        # This is now primarily handled by client.close(), which is called by client.run() on exit.
        logger.info("Bot process has finished. Cleanup should have occurred in client.close().")

Initialize()