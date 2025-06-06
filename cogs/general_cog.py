# cogs/general_cog.py
import discord
import shlex
import asyncio
import os
import aiohttp # For making HTTP requests to Twitch API
import time    # For managing Twitch token expiry
import sys
import re
import functools # For asyncio.to_thread partials
import datetime # For birthday validation
import json # For pretty-printing dicts
from bs4 import BeautifulSoup # Added for HTML parsing
from urllib.parse import urljoin # Added for resolving relative URLs
### Twitch Functionality Is Not Supported!!! ###
from discord.ext import commands
from discord.ext.commands import Context

def sanitize_command_input(input_string: str) -> list[str]:
    """
    Safely parses a command input string into a list of arguments using shlex.
    This helps prevent command injection by correctly handling quotes and shell-like syntax.

    Args:
        input_string: The raw string input for the command.

    Returns:
        A list of arguments.

    Raises:
        ValueError: If the input string has unclosed quotes or other
                    lexical errors that shlex cannot parse.
    """
    if not input_string: # Handle empty input string
        return []
    try:
        return shlex.split(input_string)
    except ValueError as e:
        # The calling command should handle this exception and inform the user.
        raise ValueError(f"Invalid command input: {e}. Please check your quotes and arguments.") from e

class GeneralCog(commands.Cog, name="General"):
    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot # Added type hint for self.bot
        # Access the logger from the bot instance
        self.logger = self.bot.logger
        # Initialize an aiohttp.ClientSession for this cog
        # This session will be used for API calls (e.g., Twitch)
        self.http_session = aiohttp.ClientSession()
        # For Twitch API token caching
        self.twitch_app_access_token: str | None = None
        self.twitch_token_expires_at: float = 0  # Stores Unix timestamp of expiry
        # Access the Alien instance from the bot
        self.alien = self.bot.alien_instance # type: ignore
        # For cyber resources command
        self.cyber_resources_file_path = "data/cyber_resources.json" # Assumes bot runs from project root
        self.cyber_resources_cache: list[dict] | None = None
        self.prompts_help = [
            # ... (your help prompts) ...
        ]

    async def cog_unload(self):
        """Called when the cog is unloaded. Clean up the HTTP session."""
        await self.http_session.close()

    async def _send_paginated_output(self, interaction: discord.Interaction, title: str, output: str, lang: str = "txt", max_messages: int = 5):
        """
        Sends potentially long output as paginated messages, respecting Discord's char limits.
        Wraps content in code blocks.
        """
        self.logger.debug(f"Sending paginated output for '{title}' with max_messages: {max_messages}")
        if not output:
            await interaction.followup.send(f"**{title}**\n```\nNo output.\n```")
            return
        # Max characters for the content within a single code block,
        # reserving space for title, " (Part X/Y)", "```lang\n", "\n```", and a small buffer.
        max_chars_for_content_block = 1850 
        lines = output.splitlines(keepends=True)
        chunks = []
        current_chunk_lines = []
        current_chunk_len = 0

        # Determine the actual content to paginate.
        # If 'lang' is specific (not md/txt) and the entire 'output' is already a single
        # fenced code block, we paginate its inner content to avoid double-fencing.
        content_to_paginate = output
        if lang.lower() not in ["md", "txt", "", "markdown", "text"]:
            # Regex to match ```optional_lang\n content \n``` for the *entire output*
            original_output_fence_match = re.match(r"^\s*```(\w*)?\s*\n(.*?)\n\s*```\s*$", output, re.DOTALL)
            if original_output_fence_match:
                extracted_content = original_output_fence_match.group(2)
                if extracted_content is not None:
                    content_to_paginate = extracted_content
                    self.logger.debug(
                        f"Original output for '{title}' was a single fenced block. "
                        f"Paginating its inner content. Specified lang for chunks: '{lang}'."
                    )
                else:
                    self.logger.warning(
                        f"Original output for '{title}' matched fence pattern, but extracted content was None. Paginating original output."
                    )
        
        lines = content_to_paginate.splitlines(keepends=True) # Re-split if content_to_paginate changed

        for line in lines:
            # If a single line is already too big, it needs to be force-split.
            if len(line) > max_chars_for_content_block:
                if current_chunk_lines: # Send off what we have so far
                    chunks.append("".join(current_chunk_lines))
                    current_chunk_lines = []
                    current_chunk_len = 0
                
                temp_line = line
                while len(temp_line) > max_chars_for_content_block:
                    chunks.append(temp_line[:max_chars_for_content_block])
                    temp_line = temp_line[max_chars_for_content_block:]
                if temp_line: # Add the remainder of the split line if it's not empty
                    current_chunk_lines.append(temp_line)
                    current_chunk_len += len(temp_line)
                continue 

            if current_chunk_len + len(line) > max_chars_for_content_block:
                chunks.append("".join(current_chunk_lines))
                current_chunk_lines = [line]
                current_chunk_len = len(line)
            else:
                current_chunk_lines.append(line)
                current_chunk_len += len(line)
        if current_chunk_lines: 
            chunks.append("".join(current_chunk_lines))
        if not chunks and output.strip(): # If output existed but chunking resulted in nothing (e.g. output was just newlines that got stripped)
            chunks.append(output.strip()) 
        if not chunks: 
             await interaction.followup.send(f"**{title}**\n```\nNo output (or output was only whitespace).\n```")
             return
        num_chunks = len(chunks)
        messages_sent = 0
        for i, chunk_content in enumerate(chunks):
            if messages_sent >= max_messages:
                self.logger.warning(f"Output for '{title}' truncated after {max_messages} messages.")
                await interaction.followup.send(f"_{discord.utils.escape_markdown(title)}: Output truncated after {max_messages} messages. The full output was longer._")
                break

            if not chunk_content.strip() and num_chunks > 1: # Skip sending if a chunk is only whitespace, unless it's the only chunk
                continue
            message_title_part = f" (Part {i+1}/{num_chunks})" if num_chunks > 1 else ""
            message_title = f"**{discord.utils.escape_markdown(title)}{discord.utils.escape_markdown(message_title_part)}**"
            
            formatted_chunk = chunk_content.strip()
            
            # Check if we are on the last allowed message and there are more chunks
            is_last_allowed_message_with_more_chunks = (messages_sent == max_messages - 1) and (i < num_chunks - 1)
            
            if is_last_allowed_message_with_more_chunks:
                formatted_chunk += f"\n\n... (Output truncated after {max_messages} messages)"

            message_body = f"```{lang}\n{formatted_chunk}\n```"
            # Conditionally wrap in code block fences
            if lang and lang.lower() not in ["md", "markdown"]:
                message_body_final = f"```{lang}\n{formatted_chunk}\n```"
            else: # For "md", "markdown", or if lang is empty/None, don't add fences
                message_body_final = formatted_chunk
            full_message = f"{message_title}\n{message_body_final}"

            if len(full_message) > 2000:
                self.logger.warning(
                    f"Message for '{title}' part {i+1} is too long ({len(full_message)} chars) even after pagination. Truncating content."
                )
                # Recalculate available space based on whether fences are used
                header_len = len(f"{message_title}\n")
                if lang and lang.lower() not in ["md", "markdown"]:
                    header_len += len(f"```{lang}\n\n```") # Add length of fences
                else:
                    header_len += 0 # No fences

                available_content_space = 2000 - header_len - 20 # -20 for " ... (truncated)"
                
                if available_content_space > 0:
                    truncated_content = formatted_chunk[:available_content_space] + " ... (truncated)"
                    if lang and lang.lower() not in ["md", "markdown"]:
                        full_message = f"{message_title}\n```{lang}\n{truncated_content}\n```"
                    else:
                        full_message = f"{message_title}\n{truncated_content}"
                else: # Should be rare, means title itself is almost 2000 chars
                    full_message = f"{message_title}\nError: Content too long to display with this title."
                    if len(full_message) > 2000: 
                        full_message = f"**{discord.utils.escape_markdown(title)}**: Error: Output too large, and title is too long to display safely."
            
            await interaction.followup.send(full_message)
            messages_sent += 1

    async def _send_paginated_output_ctx(self, ctx: Context, title: str, output: str, lang: str = "txt", max_messages: int = 5):
        """
        Sends potentially long output as paginated messages for context-based commands, respecting Discord's char limits.
        Wraps content in code blocks.
        """
        self.logger.debug(f"Sending paginated output (ctx) for '{title}' with max_messages: {max_messages}")
        if not output:
            await ctx.send(f"**{title}**\n```\nNo output.\n```")
            return

        max_chars_for_content_block = 1850  # Reserve space for title, " (Part X/Y)", "```lang\n", "\n```", buffer
        
        content_to_paginate = output
        if lang.lower() not in ["md", "txt", "", "markdown", "text"]:
            original_output_fence_match = re.match(r"^\s*```(\w*)?\s*\n(.*?)\n\s*```\s*$", output, re.DOTALL)
            if original_output_fence_match:
                extracted_content = original_output_fence_match.group(2)
                if extracted_content is not None:
                    content_to_paginate = extracted_content
                    self.logger.debug(
                        f"Original output for '{title}' (ctx) was a single fenced block. "
                        f"Paginating its inner content. Specified lang for chunks: '{lang}'."
                    )
                else:
                    self.logger.warning(
                        f"Original output for '{title}' (ctx) matched fence pattern, but extracted content was None. Paginating original output."
                    )
        
        lines = content_to_paginate.splitlines(keepends=True)
        chunks = []
        current_chunk_lines = []
        current_chunk_len = 0

        for line in lines:
            if len(line) > max_chars_for_content_block:
                if current_chunk_lines:
                    chunks.append("".join(current_chunk_lines))
                    current_chunk_lines = []
                    current_chunk_len = 0
                
                temp_line = line
                while len(temp_line) > max_chars_for_content_block:
                    chunks.append(temp_line[:max_chars_for_content_block])
                    temp_line = temp_line[max_chars_for_content_block:]
                if temp_line:
                    current_chunk_lines.append(temp_line)
                    current_chunk_len += len(temp_line)
                continue

            if current_chunk_len + len(line) > max_chars_for_content_block:
                chunks.append("".join(current_chunk_lines))
                current_chunk_lines = [line]
                current_chunk_len = len(line)
            else:
                current_chunk_lines.append(line)
                current_chunk_len += len(line)
        
        if current_chunk_lines:
            chunks.append("".join(current_chunk_lines))
        
        if not chunks and output.strip():
            chunks.append(output.strip())
        
        if not chunks:
             await ctx.send(f"**{title}**\n```\nNo output (or output was only whitespace).\n```")
             return

        num_chunks = len(chunks)
        messages_sent = 0
        for i, chunk_content in enumerate(chunks):
            if messages_sent >= max_messages:
                self.logger.warning(f"Output for '{title}' (ctx) truncated after {max_messages} messages.")
                await ctx.send(f"_{discord.utils.escape_markdown(title)}: Output truncated after {max_messages} messages. The full output was longer._")
                break

            if not chunk_content.strip() and num_chunks > 1:
                continue
            
            message_title_part = f" (Part {i+1}/{num_chunks})" if num_chunks > 1 else ""
            message_title_str = f"**{discord.utils.escape_markdown(title)}{discord.utils.escape_markdown(message_title_part)}**"
            
            formatted_chunk = chunk_content.strip()
            
            is_last_allowed_message_with_more_chunks = (messages_sent == max_messages - 1) and (i < num_chunks - 1)
            if is_last_allowed_message_with_more_chunks:
                formatted_chunk += f"\n\n... (Output truncated after {max_messages} messages)"

            message_body = f"```{lang}\n{formatted_chunk}\n```"
            # Conditionally wrap in code block fences
            if lang and lang.lower() not in ["md", "markdown"]:
                message_body_final = f"```{lang}\n{formatted_chunk}\n```"
            else: # For "md", "markdown", or if lang is empty/None, don't add fences
                message_body_final = formatted_chunk
            full_message = f"{message_title_str}\n{message_body_final}"

            if len(full_message) > 2000:
                self.logger.warning(
                    f"Message for '{title}' (ctx) part {i+1} is too long ({len(full_message)} chars) even after pagination. Truncating content."
                )
                # Recalculate available space based on whether fences are used
                header_len = len(f"{message_title_str}\n")
                if lang and lang.lower() not in ["md", "markdown"]:
                    header_len += len(f"```{lang}\n\n```") # Add length of fences
                else:
                    header_len += 0 # No fences
                available_content_space = 2000 - header_len - 20 # Buffer for " ... (truncated)"
                
                if available_content_space > 0:
                    truncated_content = formatted_chunk[:available_content_space] + " ... (truncated)"
                    if lang and lang.lower() not in ["md", "markdown"]:
                        full_message = f"{message_title_str}\n```{lang}\n{truncated_content}\n```"
                    else:
                        full_message = f"{message_title_str}\n{truncated_content}"
                else:
                    full_message = f"{message_title_str}\nError: Content too long to display with this title."
                    if len(full_message) > 2000: 
                        full_message = f"**{discord.utils.escape_markdown(title)}**: Error: Output too large, and title is too long to display safely."
            
            await ctx.send(full_message)
            messages_sent += 1

    ### DrJean Commands ###

    @commands.command(name="DrJean.tools.addBirthday", help="Adds or updates a user's birthday. Usage: $DrJean.tools.addBirthday @User YYYY-MM-DD [backup=true/false]")
    async def add_birthday_command(self, ctx: Context, user_mention: str, birthday_str: str, backup: bool = False): # Added backup
        """Adds or updates a user's birthday in the database."""
        self.logger.info(f"'{ctx.prefix}{ctx.invoked_with}' invoked by {ctx.author} for user '{user_mention}' with birthday '{birthday_str}', backup: {backup}.")

        # Parse user ID from mention or direct ID
        target_user_id: int | None = None
        if ctx.message.mentions:
            target_user = ctx.message.mentions[0]
            target_user_id = target_user.id
            self.logger.debug(f"Target user identified by mention: {target_user.name} (ID: {target_user_id})")
        else:
            try:
                target_user_id = int(user_mention)
                target_user = self.bot.get_user(target_user_id) or await self.bot.fetch_user(target_user_id) # type: ignore
                if not target_user:
                    await ctx.send(f"Could not find user with ID: {target_user_id}")
                    return
                self.logger.debug(f"Target user identified by ID: {target_user_id}")
            except ValueError:
                await ctx.send("Invalid user format. Please mention the user (e.g., @User) or provide their ID.")
                return
            except discord.NotFound:
                await ctx.send(f"Could not find user with ID: {user_mention}")
                return

        # Validate birthday format (YYYY-MM-DD)
        try:
            datetime.datetime.strptime(birthday_str, "%Y-%m-%d")
            self.logger.debug(f"Birthday string '{birthday_str}' is in valid YYYY-MM-DD format.")
        except ValueError:
            await ctx.send("Invalid birthday format. Please use YYYY-MM-DD (e.g., 2000-01-31).")
            self.logger.warning(f"Invalid birthday format provided: {birthday_str}")
            return

        if not self.bot.database: # type: ignore
            self.logger.error("Database connection is not available.")
            await ctx.send("Error: Database connection is not available. Cannot save birthday.")
            return

        try:
            async with self.bot.database.cursor() as cursor: # type: ignore
                await cursor.execute(
                    "INSERT OR REPLACE INTO user_birthdays (user_id, birthday, backup_flag) VALUES (?, ?, ?)", 
                    (target_user_id, birthday_str, int(backup)) # Store backup as int (0 or 1)
                )
            await self.bot.database.commit() # type: ignore
            await ctx.send(f"Birthday for {target_user.mention if target_user else f'user ID {target_user_id}'} has been set to {birthday_str}. Backup flag set to {backup}.")
            self.logger.info(f"Successfully added/updated birthday for user ID {target_user_id} to {birthday_str} with backup_flag={int(backup)}.")
        except Exception as e:
            self.logger.error(f"Failed to add/update birthday for user ID {target_user_id}: {e}", exc_info=True)
            await ctx.send(f"An error occurred while saving the birthday: {e}")

    async def _set_birthday_direct(self, user_id: int, birthday_str: str, backup: bool = False) -> bool: # Added backup
        """Directly sets or updates a user's birthday. For internal/TUI use."""
        self.logger.info(f"Directly setting birthday for user ID {user_id} to {birthday_str}, backup: {backup}.")
        try:
            # Validate birthday format (YYYY-MM-DD)
            datetime.datetime.strptime(birthday_str, "%Y-%m-%d")
        except ValueError:
            self.logger.warning(f"Invalid birthday format '{birthday_str}' in _set_birthday_direct.")
            return False

        if not self.bot.database: # type: ignore
            self.logger.error("Database connection not available for _set_birthday_direct.")
            return False
        try:
            async with self.bot.database.cursor() as cursor: # type: ignore
                await cursor.execute(
                    "INSERT OR REPLACE INTO user_birthdays (user_id, birthday, backup_flag) VALUES (?, ?, ?)", 
                    (user_id, birthday_str, int(backup))
                )
            await self.bot.database.commit() # type: ignore
            self.logger.info(f"Successfully set birthday for user ID {user_id} via _set_birthday_direct with backup_flag={int(backup)}.")
            return True
        except Exception as e:
            self.logger.error(f"Failed to set birthday for user ID {user_id} via _set_birthday_direct: {e}", exc_info=True)
            return False

    @commands.command(name="DrJean.tools.kys")
    @commands.is_owner() # Restrict this command to the bot owner
    async def kys_command(self,ctx:Context):
        """Terminates The Bot. (Owner Only)"""
        self.logger.info(f"'{ctx.prefix}{ctx.invoked_with}' command invoked by {ctx.author} (ID: {ctx.author.id}). Initiating bot shutdown.")
        await ctx.send("Shutting down... Goodbye! (My dad says i'm a good boi!)")
        await self.bot.close() # Gracefully close the bot

    @kys_command.error
    async def kys_command_error(self, ctx: Context, error):
        if isinstance(error, commands.NotOwner):
            await ctx.send("You must be the bot owner to use this command.")
        else:
            self.logger.error(f"An unexpected error occurred in kys_command: {error}", exc_info=True)
            await ctx.send("An unexpected error occurred while trying to shut down.")

    @commands.command(name="DrJean.tools.restart")
    @commands.is_owner()
    async def restart_command(self, ctx: Context):
        """Restarts the bot. (Owner Only)"""
        self.logger.info(f"'{ctx.prefix}{ctx.invoked_with}' command invoked by {ctx.author} (ID: {ctx.author.id}). Initiating bot restart.")
        await ctx.send("Restarting the bot... Please wait.")

        try:
            # Define an async helper function to perform the restart steps.
            # This allows the current command context to finish before the bot process is replaced.
            async def _do_restart():
                await self.bot.close()  # Gracefully close the bot (handles DB, tasks, etc.)
                self.logger.info("Bot closed. Executing os.execv to restart the bot script.")
                # Replace the current process with a new instance of the bot script
                os.execv(sys.executable, [sys.executable] + sys.argv)

            # Schedule the restart logic to run after the current event loop iteration.
            self.bot.loop.create_task(_do_restart())

        except Exception as e:
            self.logger.critical(f"Error during bot restart sequence: {e}", exc_info=True)
            # This message might not be sent if ctx is no longer valid after an error during close/execv setup
            try: await ctx.send(f"An error occurred during the restart process: {e}")
            except: pass # Ignore if sending fails

    @commands.command(name="DrJean.tools.test")
    async def test_command(self, ctx: Context):
        """A simple test command within a cog."""
        self.logger.info(f"Cog 'test' command invoked by {ctx.author}.")
        await ctx.send(f"It Worked from the GeneralCog, {ctx.author.mention}!")

    ### SQL Commands ###
    _banned_sql_keywords_for_select = re.compile(
        r'\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|VACUUM|REINDEX|PRAGMA|EXEC|TRANSACTION|COMMIT|ROLLBACK|SAVEPOINT|RELEASE|WITH)\b',
        re.IGNORECASE
    )
    _banned_sql_keywords_for_edit_reset = re.compile(
        r'\b(INSERT|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|VACUUM|REINDEX|PRAGMA|EXEC|TRANSACTION|COMMIT|ROLLBACK|SAVEPOINT|RELEASE|WITH|SELECT)\b',
        re.IGNORECASE
    )
    _banned_sql_keywords_for_remove = re.compile(
        r'\b(INSERT|UPDATE|DROP|ALTER|CREATE|ATTACH|DETACH|VACUUM|REINDEX|PRAGMA|EXEC|TRANSACTION|COMMIT|ROLLBACK|SAVEPOINT|RELEASE|SELECT)\b',
        re.IGNORECASE
    )

    @commands.command(name="DrJean.sql.listTables", help="Lists all tables in the database.")
    @commands.is_owner()
    async def list_tables_command(self, ctx: Context):
        self.logger.info(f"'{ctx.prefix}{ctx.invoked_with}' invoked by {ctx.author}.")
        if not self.bot.database: # type: ignore
            await ctx.send("Error: Database connection is not available.")
            return

        try:
            async with self.bot.database.cursor() as cursor: # type: ignore
                await cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
                tables = await cursor.fetchall()
            
            if tables:
                table_names = "\n".join([row[0] for row in tables])
                await self._send_paginated_output_ctx(ctx, "Database Tables", table_names)
            else:
                await ctx.send("No tables found in the database.")
        except Exception as e:
            self.logger.error(f"Error listing tables: {e}", exc_info=True)
            await ctx.send(f"An error occurred while listing tables: {e}")

    @commands.command(name="DrJean.sql.getTableSchema", help="Shows the schema for a specified table. Usage: $DrJean.sql.getTableSchema <table_name>")
    @commands.is_owner()
    async def get_table_schema_command(self, ctx: Context, table_name: str):
        self.logger.info(f"'{ctx.prefix}{ctx.invoked_with}' invoked by {ctx.author} for table '{table_name}'.")
        if not self.bot.database: # type: ignore
            await ctx.send("Error: Database connection is not available.")
            return

        if not re.match(r"^[a-zA-Z0-9_]+$", table_name):
            await ctx.send(f"Invalid table name format: '{table_name}'. Only alphanumeric characters and underscores are allowed.")
            return

        try:
            async with self.bot.database.cursor() as cursor: # type: ignore
                await cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
                if not await cursor.fetchone():
                    await ctx.send(f"Table '{table_name}' not found.")
                    return

                await cursor.execute(f"PRAGMA table_info('{table_name}');")
                schema_info = await cursor.fetchall()
        
            if schema_info:
                output_lines = [f"Schema for table: {table_name}"]
                for row in schema_info: # cid, name, type, notnull, dflt_value, pk
                    output_lines.append(
                        f"- Name: {row[1]}, Type: {row[2]}, NotNull: {bool(row[3])}, Default: {row[4]}, PK: {bool(row[5])}"
                    )
                await self._send_paginated_output_ctx(ctx, f"Schema for {table_name}", "\n".join(output_lines))
            else:
                await ctx.send(f"Could not retrieve schema for table '{table_name}'.")
        except Exception as e:
            self.logger.error(f"Error getting table schema for '{table_name}': {e}", exc_info=True)
            await ctx.send(f"An error occurred while getting schema for '{table_name}': {e}")

    @commands.command(name="DrJean.sql.executeSelect", help="Executes a read-only SELECT query. Usage: $DrJean.sql.executeSelect <query>")
    @commands.is_owner()
    async def execute_select_command(self, ctx: Context, *, query: str):
        self.logger.info(f"'{ctx.prefix}{ctx.invoked_with}' invoked by {ctx.author} with query '{query[:100]}...'.")
        clean_query = query.strip()

        if not clean_query.lower().startswith("select"):
            await ctx.send("Error: Query must be a SELECT statement.")
            return
        if GeneralCog._banned_sql_keywords_for_select.search(clean_query):
            await ctx.send("Error: Query contains disallowed keywords (e.g., UPDATE, DELETE, PRAGMA, WITH). Only simple SELECT statements are permitted.")
            return
        if not self.bot.database: # type: ignore
            await ctx.send("Error: Database connection is not available.")
            return

        try:
            async with self.bot.database.cursor() as cursor: # type: ignore
                await cursor.execute(clean_query)
                rows = await cursor.fetchall()
                
                if not rows:
                    await ctx.send("Query executed successfully, but returned no results.")
                    return

                column_names = [description[0] for description in cursor.description] if cursor.description else []
                results_as_dicts = [dict(zip(column_names, row)) for row in rows]
                output_json = json.dumps(results_as_dicts, indent=2, default=str)

                await self._send_paginated_output_ctx(ctx, f"Query Results: {clean_query[:50]}...", output_json, lang="json")
        except Exception as e:
            self.logger.error(f"Error executing SELECT query '{clean_query}': {e}", exc_info=True)
            await self._send_paginated_output_ctx(ctx, "Query Execution Error", str(e), lang="txt")

    @commands.command(name="DrJean.sql.executeEdit", help="Executes an UPDATE SQL query. Usage: $DrJean.sql.executeEdit <UPDATE_query>")
    @commands.is_owner()
    async def execute_edit_command(self, ctx: Context, *, query: str):
        self.logger.info(f"'{ctx.prefix}{ctx.invoked_with}' invoked by {ctx.author} with query '{query[:100]}...'.")
        clean_query = query.strip()

        if not clean_query.lower().startswith("update"):
            await ctx.send("Error: Query must be an UPDATE statement.")
            return
        if GeneralCog._banned_sql_keywords_for_edit_reset.search(clean_query):
            await ctx.send("Error: Query contains disallowed keywords. Only UPDATE statements are permitted for editing.")
            return
        if not self.bot.database: # type: ignore
            await ctx.send("Error: Database connection is not available.")
            return

        try:
            async with self.bot.database.cursor() as cursor: # type: ignore
                await cursor.execute(clean_query)
                rows_affected = cursor.rowcount
            await self.bot.database.commit() # type: ignore
            
            await ctx.send(f"UPDATE query executed successfully. {rows_affected} row(s) affected.")
            self.logger.info(f"Successfully executed UPDATE query. {rows_affected} row(s) affected. Query: {clean_query}")
        except Exception as e:
            self.logger.error(f"Error executing UPDATE query '{clean_query}': {e}", exc_info=True)
            await self._send_paginated_output_ctx(ctx, "Query Execution Error", str(e), lang="txt")

    @commands.command(name="DrJean.sql.executeReset", help="Executes an UPDATE SQL query, typically for resetting data. Usage: $DrJean.sql.executeReset <UPDATE_query>")
    @commands.is_owner()
    async def execute_reset_command(self, ctx: Context, *, query: str):
        self.logger.info(f"'{ctx.prefix}{ctx.invoked_with}' invoked by {ctx.author} with query '{query[:100]}...'.")
        clean_query = query.strip()

        if not clean_query.lower().startswith("update"):
            await ctx.send("Error: Query must be an UPDATE statement for resetting data.")
            return
        if GeneralCog._banned_sql_keywords_for_edit_reset.search(clean_query):
            await ctx.send("Error: Query contains disallowed keywords. Only UPDATE statements are permitted for resetting.")
            return
        if not self.bot.database: # type: ignore
            await ctx.send("Error: Database connection is not available.")
            return

        try:
            async with self.bot.database.cursor() as cursor: # type: ignore
                await cursor.execute(clean_query)
                rows_affected = cursor.rowcount
            await self.bot.database.commit() # type: ignore

            await ctx.send(f"UPDATE (reset) query executed successfully. {rows_affected} row(s) affected.")
            self.logger.info(f"Successfully executed UPDATE (reset) query. {rows_affected} row(s) affected. Query: {clean_query}")
        except Exception as e:
            self.logger.error(f"Error executing UPDATE (reset) query '{clean_query}': {e}", exc_info=True)
            await self._send_paginated_output_ctx(ctx, "Query Execution Error", str(e), lang="txt")

    @commands.command(name="DrJean.sql.executeRemove", help="Executes a DELETE SQL query. Usage: $DrJean.sql.executeRemove <DELETE_query>")
    @commands.is_owner()
    async def execute_remove_command(self, ctx: Context, *, query: str):
        self.logger.info(f"'{ctx.prefix}{ctx.invoked_with}' invoked by {ctx.author} with query '{query[:100]}...'.")
        clean_query = query.strip()

        if not clean_query.lower().startswith("delete"):
            await ctx.send("Error: Query must be a DELETE statement.")
            return
        if GeneralCog._banned_sql_keywords_for_remove.search(clean_query):
            await ctx.send("Error: Query contains disallowed keywords. Only DELETE statements are permitted for removing data.")
            return
        if not self.bot.database: # type: ignore
            await ctx.send("Error: Database connection is not available.")
            return

        try:
            async with self.bot.database.cursor() as cursor: # type: ignore
                await cursor.execute(clean_query)
                rows_affected = cursor.rowcount
            await self.bot.database.commit() # type: ignore

            await ctx.send(f"DELETE query executed successfully. {rows_affected} row(s) affected.")
            self.logger.info(f"Successfully executed DELETE query. {rows_affected} row(s) affected. Query: {clean_query}")
        except Exception as e:
            self.logger.error(f"Error executing DELETE query '{clean_query}': {e}", exc_info=True)
            await self._send_paginated_output_ctx(ctx, "Query Execution Error", str(e), lang="txt")

        
    # Define tables that are aware of the backup_flag
    _BACKUP_AWARE_TABLES = ["user_birthdays", "jack_ideas", "user_emotional_profiles", "original_characters"] # Add other tables as needed

    @commands.command(name="DrJean.sql.backup", help="Backs up data from flagged tables to a JSON file.")
    @commands.is_owner()
    async def backup_sql_data_command(self, ctx: Context):
        self.logger.info(f"'{ctx.prefix}{ctx.invoked_with}' invoked by {ctx.author}.")
        if not self.bot.database: # type: ignore
            await ctx.send("Error: Database connection is not available.")
            return

        backup_data = {}
        problematic_tables = []

        for table_name in self._BACKUP_AWARE_TABLES:
            try:
                async with self.bot.database.cursor() as cursor: # type: ignore
                    # Check if backup_flag column exists
                    await cursor.execute(f"PRAGMA table_info('{table_name}');")
                    columns_info = await cursor.fetchall()
                    column_names = [col_info[1] for col_info in columns_info]

                    if "backup_flag" not in column_names:
                        self.logger.warning(f"Table '{table_name}' does not have a 'backup_flag' column. Skipping for backup.")
                        problematic_tables.append(f"{table_name} (missing backup_flag column)")
                        continue
                    
                    # Fetch only rows marked for backup and get their column description
                    await cursor.execute(f"SELECT * FROM {table_name} WHERE backup_flag = 1;")
                    current_description = cursor.description # Capture description from this query
                    rows = await cursor.fetchall()
                    
                    actual_column_names = [desc[0] for desc in current_description] if current_description else []

                    if rows:
                        if not actual_column_names:
                            self.logger.error(f"Could not get column names for table '{table_name}' despite having rows. Skipping data for this table.")
                            problematic_tables.append(f"{table_name} (error: could not get column names)")
                            continue
                        backup_data[table_name] = [dict(zip(actual_column_names, row)) for row in rows]
                        self.logger.info(f"Fetched {len(rows)} rows from '{table_name}' for backup.")
                    else:
                        self.logger.info(f"No rows marked for backup (backup_flag=1) in '{table_name}'.")
                        backup_data[table_name] = [] # Still include table in backup if it's backup-aware
            except Exception as e:
                self.logger.error(f"Error processing table '{table_name}' for backup: {e}", exc_info=True)
                problematic_tables.append(f"{table_name} (error: {e})")
        
        if not backup_data and not problematic_tables:
            await ctx.send("No data marked for backup found in any of the backup-aware tables.")
            return
        if not backup_data and problematic_tables:
            await ctx.send(f"Could not back up any data. Problems encountered with tables: {', '.join(problematic_tables)}")
            return


        # Ensure backup directory exists
        backup_dir = "backups"
        os.makedirs(backup_dir, exist_ok=True)
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"jeanbot_db_backup_{timestamp}.json"
        backup_filepath = os.path.join(backup_dir, backup_filename)

        try:
            with open(backup_filepath, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, indent=2, default=str) # default=str for datetime etc.
            
            summary_lines = [f"Database backup successful! Saved to `{backup_filepath}`"]
            for table, data_list in backup_data.items():
                summary_lines.append(f"- Table `{table}`: {len(data_list)} row(s) backed up.")
            if problematic_tables:
                summary_lines.append("\n**Issues encountered with some tables:**")
                for pt in problematic_tables:
                    summary_lines.append(f"- {pt}")
            
            await self._send_paginated_output_ctx(ctx, "Backup Complete", "\n".join(summary_lines))

        except Exception as e:
            self.logger.error(f"Error writing backup file to '{backup_filepath}': {e}", exc_info=True)
            await ctx.send(f"An error occurred while writing the backup file: {e}")


    @commands.command(name="DrJean.sql.flush", help="Removes data from tables where backup_flag is not set.")
    @commands.is_owner()
    async def flush_sql_data_command(self, ctx: Context, confirm: str = ""):
        self.logger.info(f"'{ctx.prefix}{ctx.invoked_with}' invoked by {ctx.author}.")

        if confirm.lower() != "yes_i_am_sure":
            await ctx.send(f"This is a destructive operation. To confirm, run the command again with `yes_i_am_sure` as the argument: `{ctx.prefix}DrJean.sql.flush yes_i_am_sure`")
            return

        if not self.bot.database: # type: ignore
            await ctx.send("Error: Database connection is not available.")
            return

        flushed_summary = []
        problematic_tables_flush = []
        total_rows_deleted = 0

        for table_name in self._BACKUP_AWARE_TABLES:
            try:
                async with self.bot.database.cursor() as cursor: # type: ignore
                    # Check if backup_flag column exists
                    await cursor.execute(f"PRAGMA table_info('{table_name}');")
                    columns_info = await cursor.fetchall()
                    column_names = [col_info[1] for col_info in columns_info]

                    if "backup_flag" not in column_names:
                        self.logger.warning(f"Table '{table_name}' does not have a 'backup_flag' column. Skipping for flush.")
                        problematic_tables_flush.append(f"{table_name} (missing backup_flag column)")
                        continue

                    # Delete rows where backup_flag is 0 or NULL
                    await cursor.execute(f"DELETE FROM {table_name} WHERE backup_flag = 0 OR backup_flag IS NULL;")
                    rows_affected = cursor.rowcount
                await self.bot.database.commit() # type: ignore
                
                if rows_affected > 0:
                    flushed_summary.append(f"- Table `{table_name}`: {rows_affected} row(s) flushed.")
                    total_rows_deleted += rows_affected
                else:
                    flushed_summary.append(f"- Table `{table_name}`: No rows to flush (all were marked for backup or table was empty).")
                self.logger.info(f"Flushed {rows_affected} rows from '{table_name}'.")

            except Exception as e:
                self.logger.error(f"Error processing table '{table_name}' for flush: {e}", exc_info=True)
                problematic_tables_flush.append(f"{table_name} (error: {e})")
        
        response_lines = []
        if total_rows_deleted > 0:
            response_lines.append(f"Flush operation complete. Total rows deleted: {total_rows_deleted}.")
        else:
            response_lines.append("Flush operation complete. No rows were deleted (either all data was marked for backup or tables were empty/unflagged).")
        
        if flushed_summary:
            response_lines.append("\n**Details per table:**")
            response_lines.extend(flushed_summary)
        
        if problematic_tables_flush:
            response_lines.append("\n**Issues encountered with some tables during flush:**")
            for pt_flush in problematic_tables_flush:
                response_lines.append(f"- {pt_flush}")
        
        await self._send_paginated_output_ctx(ctx, "Flush Operation Summary", "\n".join(response_lines))

    async def _get_twitch_app_access_token(self, force_refresh: bool = False) -> str | None:
        """
        Retrieves a Twitch App Access Token, caching it and refreshing if necessary.
        Ensure TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET are in your environment variables.
        """
        client_id = os.getenv("TWITCH_CLIENT_ID")
        client_secret = os.getenv("TWITCH_CLIENT_SECRET")

        if not client_id or not client_secret:
            self.logger.error("TWITCH_CLIENT_ID or TWITCH_CLIENT_SECRET not found in environment variables.")
            return None

        current_time = time.time()
        # Refresh if token is missing, expired, or nearing expiry (e.g., within 5 minutes / 300 seconds)
        if force_refresh or not self.twitch_app_access_token or current_time >= (self.twitch_token_expires_at - 300):
            self.logger.info("Fetching/Refreshing Twitch App Access Token...")
            url = "https://id.twitch.tv/oauth2/token"
            params = {
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials"
            }
            try:
                # Use the cog's http_session
                async with self.http_session.post(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.twitch_app_access_token = data.get("access_token")
                        expires_in = data.get("expires_in") # expires_in is in seconds
                        if self.twitch_app_access_token and expires_in is not None:
                            self.twitch_token_expires_at = current_time + expires_in
                            self.logger.info(f"Successfully obtained Twitch App Access Token. Expires in {expires_in} seconds.")
                        else:
                            self.logger.error(f"Failed to parse token or expiry from Twitch response: {data}")
                            self.twitch_app_access_token = None
                            return None
                    else:
                        error_text = await resp.text()
                        self.logger.error(f"Failed to get Twitch App Access Token: {resp.status} - {error_text}")
                        self.twitch_app_access_token = None
                        return None
            except aiohttp.ClientError as e:
                self.logger.error(f"aiohttp.ClientError while getting Twitch App Access Token: {e}", exc_info=True)
                self.twitch_app_access_token = None
                return None
            except Exception as e:
                self.logger.error(f"Unexpected exception while getting Twitch App Access Token: {e}", exc_info=True)
                self.twitch_app_access_token = None
                return None
        elif self.twitch_app_access_token:
            self.logger.debug("Using cached Twitch App Access Token.")
            
        return self.twitch_app_access_token


    ### Slash Commands ###
    @discord.app_commands.command(name="nmap", description="Run an nmap scan with arguments on a target host.")
    async def run_nmap_command(self, interaction: discord.Interaction, arguments: str):
        """Runs an nmap scan with the provided arguments."""
        await interaction.response.defer(thinking=True) # Acknowledge the command immediately
        self.logger.info(f"Slash command '/nmap' invoked by {interaction.user} with args: '{arguments}'")
        try:
            sanitized_args = sanitize_command_input(arguments)
        except ValueError as e:
            await interaction.followup.send(f"Error in command arguments: {e}")
            return
        if not sanitized_args:
            await interaction.followup.send("Please provide arguments for nmap. Example: `target.com -p 80,443 -sV`")
            return
        # The base command is fixed, user provides only the arguments
        base_command = "nmap"
        full_command = [base_command] + sanitized_args
        self.logger.info(f"Attempting to run command: {' '.join(full_command)}")
        lanCheck = False
        for i in full_command:
            if str(i).startswith("192.168"): lanCheck = True
            elif str(i).startswith("127.0"): lanCheck = True
        if lanCheck == True:
            await interaction.followup.send(":scream_cat: You really think I would let you scan my network???... Nice Try Fed...")
            return
        try:
            process = await asyncio.create_subprocess_exec(
                *full_command, # Pass the command and its arguments
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await process.communicate() # No input needed for nmap via stdin here
            
            if process.returncode == 0:
                output = stdout_bytes.decode(errors='replace').strip()
                await self._send_paginated_output(interaction, "Nmap scan complete", output, lang="txt")
            else:
                error_output = stderr_bytes.decode(errors='replace').strip()
                title = f"Nmap command failed (code {process.returncode})"
                await self._send_paginated_output(interaction, title, error_output, lang="txt")
        except FileNotFoundError:
            await interaction.followup.send("Error: The 'nmap' command was not found on the system where the bot is running.")
            self.logger.error("The 'nmap' executable was not found on the system.")
        except Exception as e:
            await interaction.followup.send(f"An unexpected error occurred while trying to run the command: {e}")
            self.logger.error(f"Error running command {' '.join(full_command)}: {e}", exc_info=True)

    @discord.app_commands.command(name="whois", description="Perform a WHOIS lookup for a domain.")
    async def run_whois_command(self, interaction: discord.Interaction, domain: str):
        """Performs a WHOIS lookup for the given domain."""
        await interaction.response.defer(thinking=True) # Acknowledge the command immediately
        self.logger.info(f"Slash command '/whois' invoked by {interaction.user} for domain: '{domain}'")

        if not domain or domain.isspace():
            await interaction.followup.send("Please provide a domain name to lookup. Example: `example.com`")
            return

        # Basic check to prevent command injection with the domain argument,
        # though `asyncio.create_subprocess_exec` handles arguments safely.
        # More robust domain validation could be added if needed.
        if any(char in domain for char in ";&|`$()<>"):
            await interaction.followup.send(f"Invalid characters in domain name: '{domain}'.")
            self.logger.warning(f"Potentially unsafe characters in domain for /whois: {domain}")
            return

        base_command = "whois64.exe" # As specified
        full_command = [base_command, domain.strip()]

        self.logger.info(f"Attempting to run command: {' '.join(full_command)}")

        try:
            process = await asyncio.create_subprocess_exec(
                *full_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await process.communicate()

            if process.returncode == 0:
                output = stdout_bytes.decode(errors='replace').strip()
                await self._send_paginated_output(interaction, f"WHOIS lookup for: {domain}", output, lang="txt")
            else:
                error_output = stderr_bytes.decode(errors='replace').strip()
                title = f"WHOIS command for '{domain}' failed (code {process.returncode})"
                await self._send_paginated_output(interaction, title, error_output, lang="txt")
        except FileNotFoundError:
            await interaction.followup.send(f"Error: The '{base_command}' command was not found on the system where the bot is running.")
            self.logger.error(f"The '{base_command}' executable was not found on the system.")
        except Exception as e:
            await interaction.followup.send(f"An unexpected error occurred while trying to run the WHOIS command: {e}")
            self.logger.error(f"Error running WHOIS command {' '.join(full_command)}: {e}", exc_info=True)

    @discord.app_commands.command(name="searchsploit", description="Run searchsploit in WSL Kali with arguments.")
    async def run_searchsploit_command(self, interaction: discord.Interaction, arguments: str):
        """Runs searchsploit in WSL Kali and then attempts to shut down WSL."""
        await interaction.response.defer(thinking=True)
        self.logger.info(f"Slash command '/searchsploit' invoked by {interaction.user} with args: '{arguments}'")

        try:
            sanitized_args = sanitize_command_input(arguments)
        except ValueError as e:
            await interaction.followup.send(f"Error in command arguments: {e}")
            return

        if not sanitized_args:
            await interaction.followup.send("Please provide arguments for searchsploit. Example: `ssh 2.0` or `wordpress plugin 4.0`")
            return

        searchsploit_base_cmd = ["wsl", "-d", "kali-linux", "-e", "searchsploit"]
        searchsploit_full_cmd = searchsploit_base_cmd + sanitized_args
        shutdown_cmd = ["wsl", "--shutdown"]

        searchsploit_output = ""
        searchsploit_error_output = ""
        searchsploit_success = False

        try:
            self.logger.info(f"Attempting to run command: {' '.join(searchsploit_full_cmd)}")
            process_searchsploit = await asyncio.create_subprocess_exec(
                *searchsploit_full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await process_searchsploit.communicate()

            if process_searchsploit.returncode == 0:
                searchsploit_output = stdout_bytes.decode(errors='replace').strip()
                searchsploit_success = True
            else:
                searchsploit_error_output = stderr_bytes.decode(errors='replace').strip()
                if stdout_bytes: # Sometimes output is on stdout even with errors
                    searchsploit_output = stdout_bytes.decode(errors='replace').strip()
                self.logger.warning(f"Searchsploit command failed with code {process_searchsploit.returncode}. Error: {searchsploit_error_output}")

        except FileNotFoundError:
            await interaction.followup.send("Error: The 'wsl' command was not found on the system where the bot is running. Cannot execute SearchSploit or shutdown WSL.")
            self.logger.error("The 'wsl' executable was not found on the system.")
            return # Exit early, no point in trying shutdown if wsl isn't there
        except Exception as e:
            error_message = f"An unexpected error occurred while trying to run SearchSploit: {e}"
            await interaction.followup.send(error_message)
            self.logger.error(f"Error running SearchSploit command {' '.join(searchsploit_full_cmd)}: {e}", exc_info=True)
            # We still proceed to the finally block to attempt WSL shutdown
        finally:
            self.logger.info(f"Attempting to run WSL shutdown command: {' '.join(shutdown_cmd)}")
            try:
                process_shutdown = await asyncio.create_subprocess_exec(*shutdown_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                shutdown_stdout, shutdown_stderr = await process_shutdown.communicate()
                if process_shutdown.returncode == 0:
                    self.logger.info(f"WSL shutdown command executed successfully. Output (if any): {shutdown_stdout.decode(errors='replace').strip()}")
                else:
                    self.logger.error(f"WSL shutdown command failed with code {process_shutdown.returncode}. Error: {shutdown_stderr.decode(errors='replace').strip()} Output: {shutdown_stdout.decode(errors='replace').strip()}")
            except Exception as e_shutdown:
                self.logger.error(f"An error occurred during WSL shutdown: {e_shutdown}", exc_info=True)

        # Prepare and send the results from searchsploit
        if searchsploit_success:
            title = "SearchSploit Results"
            content_to_send = searchsploit_output if searchsploit_output else "SearchSploit ran successfully but produced no output."
        else:
            title = f"SearchSploit Command Failed"
            full_error_details = []
            if searchsploit_output: full_error_details.append(f"SearchSploit Output (if any):\n{searchsploit_output}")
            if searchsploit_error_output: full_error_details.append(f"SearchSploit Error Output:\n{searchsploit_error_output}")
            
            content_to_send = "\n\n".join(full_error_details)
            if not content_to_send: # If both output and error are empty
                content_to_send = "SearchSploit command failed and produced no specific output or error messages. WSL might not be configured correctly or searchsploit had an internal issue."

        await self._send_paginated_output(interaction, title, content_to_send, lang="txt")

    @discord.app_commands.command(name="sherlock", description="Run Sherlock OSINT tool in WSL Kali for a username.")
    @discord.app_commands.describe(username="The username to search for across social networks.")
    async def run_sherlock_command(self, interaction: discord.Interaction, username: str):
        """Runs Sherlock in WSL Kali for the given username and then attempts to shut down WSL."""
        await interaction.response.defer(thinking=True)
        self.logger.info(f"Slash command '/sherlock' invoked by {interaction.user} for username: '{username}'")

        if not username or username.isspace():
            await interaction.followup.send("Please provide a username to search for.")
            return

        # Sanitize the username argument. For a single username, direct sanitization might be simpler,
        # but using sanitize_command_input keeps it consistent if more complex args were ever needed.
        try:
            # sanitize_command_input expects a string and returns a list.
            # For a single username, we'll pass it as a string and take the first element.
            sanitized_username_list = sanitize_command_input(username)
            if not sanitized_username_list: # Should not happen if username is not empty
                await interaction.followup.send("Invalid username provided after sanitization.")
                return
            sanitized_username = sanitized_username_list[0]
        except ValueError as e:
            await interaction.followup.send(f"Error in username argument: {e}")
            return

        sherlock_base_cmd = ["wsl", "-d", "kali-linux", "-e", "sherlock"]
        sherlock_full_cmd = sherlock_base_cmd + [sanitized_username] # Pass sanitized username as a list element
        shutdown_cmd = ["wsl", "--shutdown"]

        sherlock_output = ""
        sherlock_error_output = ""
        sherlock_success = False

        try:
            self.logger.info(f"Attempting to run command: {' '.join(sherlock_full_cmd)}")
            process_sherlock = await asyncio.create_subprocess_exec(
                *sherlock_full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await process_sherlock.communicate()

            if process_sherlock.returncode == 0:
                sherlock_output = stdout_bytes.decode(errors='replace').strip()
                sherlock_success = True
            else:
                sherlock_error_output = stderr_bytes.decode(errors='replace').strip()
                if stdout_bytes: # Sherlock might output to stdout even on error (e.g., username not found)
                    sherlock_output = stdout_bytes.decode(errors='replace').strip()
                self.logger.warning(f"Sherlock command failed with code {process_sherlock.returncode}. Error: {sherlock_error_output}")

        except FileNotFoundError:
            await interaction.followup.send("Error: The 'wsl' command was not found. Cannot execute Sherlock or shutdown WSL.")
            self.logger.error("The 'wsl' executable was not found on the system.")
            return
        except Exception as e:
            await interaction.followup.send(f"An unexpected error occurred while trying to run Sherlock: {e}")
            self.logger.error(f"Error running Sherlock command {' '.join(sherlock_full_cmd)}: {e}", exc_info=True)
            # Proceed to finally for WSL shutdown attempt
        finally:
            self.logger.info(f"Attempting to run WSL shutdown command: {' '.join(shutdown_cmd)}")
            try:
                process_shutdown = await asyncio.create_subprocess_exec(*shutdown_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                shutdown_stdout, shutdown_stderr = await process_shutdown.communicate()
                if process_shutdown.returncode == 0:
                    self.logger.info(f"WSL shutdown command executed successfully. Output (if any): {shutdown_stdout.decode(errors='replace').strip()}")
                else:
                    self.logger.error(f"WSL shutdown command failed with code {process_shutdown.returncode}. Error: {shutdown_stderr.decode(errors='replace').strip()} Output: {shutdown_stdout.decode(errors='replace').strip()}")
            except Exception as e_shutdown:
                self.logger.error(f"An error occurred during WSL shutdown: {e_shutdown}", exc_info=True)

        if sherlock_success:
            title = f"Sherlock Results for '{sanitized_username}'"
            content_to_send = sherlock_output if sherlock_output else f"Sherlock ran successfully for '{sanitized_username}' but produced no output (username might not be found on any platforms)."
        else:
            title = f"Sherlock Command Failed for '{sanitized_username}'"
            full_error_details = []
            if sherlock_output: full_error_details.append(f"Sherlock Output (if any):\n{sherlock_output}")
            if sherlock_error_output: full_error_details.append(f"Sherlock Error Output:\n{sherlock_error_output}")
            content_to_send = "\n\n".join(full_error_details)
            if not content_to_send:
                content_to_send = "Sherlock command failed and produced no specific output or error messages. WSL or Sherlock might not be configured correctly."

        await self._send_paginated_output(interaction, title, content_to_send, lang="txt")

    @discord.app_commands.command(name="msfvenom", description="Generate payloads/shellcode using msfvenom.")
    @discord.app_commands.describe(arguments="Arguments for msfvenom (e.g., -p windows/x64/meterpreter/reverse_tcp LHOST=... LPORT=...). Do NOT use -o, --out, -x, or --template.")
    async def run_msfvenom_command(self, interaction: discord.Interaction, arguments: str):
        """Generates payloads/shellcode using msfvenom, ensuring output is to stdout."""
        await interaction.response.defer(thinking=True)
        self.logger.info(f"Slash command '/msfvenom' invoked by {interaction.user} with args: '{arguments}'")

        try:
            sanitized_args = sanitize_command_input(arguments)
        except ValueError as e:
            await interaction.followup.send(f"Error in command arguments: {e}")
            return

        if not sanitized_args:
            await interaction.followup.send(
                "Please provide arguments for msfvenom. Example: `-p windows/x64/shell_reverse_tcp LHOST=your.ip LPORT=4444 -f exe`"
            )
            return

        # Security: Ensure msfvenom outputs to stdout and doesn't write files or use executable templates on the bot server.
        # Disallow flags like -o (output file) and -x (template executable).
        disallowed_flags_present = {"-o", "--out", "-x", "--template"}
        for arg_token in sanitized_args:
            if arg_token in disallowed_flags_present:
                await interaction.followup.send(
                    f"Error: The msfvenom argument '{arg_token}' is disallowed for security reasons "
                    "(prevents writing files or using executable templates on the bot server). "
                    "Payloads are generated to standard output."
                )
                self.logger.warning(
                    f"Disallowed msfvenom argument '{arg_token}' used by {interaction.user}."
                )
                return

        wsl_msfvenom_cmd_parts = ["wsl", "-d", "kali-linux", "-e", "msfvenom"]
        full_command = wsl_msfvenom_cmd_parts + sanitized_args

        self.logger.info(f"Attempting to run command: {' '.join(full_command)}")

        try:
            process = await asyncio.create_subprocess_exec(
                *full_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=300.0) # 5 min timeout
            except asyncio.TimeoutError:
                self.logger.error(f"msfvenom command {' '.join(full_command)} timed out after 300s.")
                try:
                    process.kill()
                    await process.wait()
                except ProcessLookupError: pass # Already terminated
                except Exception as e_kill: self.logger.error(f"Error killing timed-out msfvenom process: {e_kill}")
                await interaction.followup.send("Error: The msfvenom command timed out (5 minutes). Please try simpler arguments or check msfvenom performance.")
                return

            if process.returncode == 0:
                output_str = stdout_bytes.decode(errors='replace').strip()
                if not output_str: # Successful but no stdout
                    output_str = "msfvenom command succeeded but produced no standard output. Check arguments if output was expected."
                    stderr_decoded_str = stderr_bytes.decode(errors='replace').strip()
                    if stderr_decoded_str: # Include stderr if any, as it might contain info/warnings
                        output_str += f"\n\nStandard Error (if any):\n{stderr_decoded_str}"
                await self._send_paginated_output(interaction, "msfvenom Output", output_str, lang="txt")
            else:
                stdout_on_error_str = stdout_bytes.decode(errors='replace').strip()
                stderr_on_error_str = stderr_bytes.decode(errors='replace').strip()
                
                error_components = []
                if stdout_on_error_str: error_components.append(f"Standard Output (if any):\n{stdout_on_error_str}")
                if stderr_on_error_str: error_components.append(f"Standard Error:\n{stderr_on_error_str}")
                error_details_str = "\n\n".join(error_components).strip()
                title = f"msfvenom command failed (code {process.returncode})"
                await self._send_paginated_output(interaction, title, error_details_str if error_details_str else "No specific error output.", lang="txt")
        except FileNotFoundError:
            # The actual command not found would be 'wsl' if this exception occurs due to the program not being found.
            await interaction.followup.send(f"Error: The 'wsl' command (required to run msfvenom via Kali Linux) was not found on the system. Ensure WSL is installed and 'wsl' is in the system's PATH.")
            self.logger.error("The 'wsl' executable (required for msfvenom) was not found on the system.")
        except Exception as e:
            await interaction.followup.send(f"An unexpected error occurred while trying to run the msfvenom command: {e}")
            self.logger.error(f"Error running msfvenom command {' '.join(full_command)}: {e}", exc_info=True)

    @discord.app_commands.command(name="greet", description="Sends a friendly greeting using a slash command!")
    async def greet_slash_command(self, interaction: discord.Interaction):
        """Sends a greeting via slash command."""
        self.logger.info(f"Slash command '/greet' invoked by {interaction.user} (ID: {interaction.user.id}).")
        await interaction.response.send_message(f"Hello {interaction.user.mention}! (You're Not My Dad!! Stranger Danger!!!)")
    
    @discord.app_commands.command(name="manual", description="Displays a manual of all available slash commands.")
    async def manual_slash_command(self, interaction: discord.Interaction):
        """Displays a detailed manual of all registered slash commands."""
        await interaction.response.defer(thinking=True)
        self.logger.info(f"Slash command '/manual' invoked by {interaction.user} (ID: {interaction.user.id}).")

        help_parts = ["# Slash Command Manual\n"]
        # Get global commands. If you have guild-specific commands, you might need to specify the guild.
        # commands = await self.bot.tree.fetch_commands() # To get commands directly from Discord API if needed
        commands = self.bot.tree.get_commands() # Gets currently registered commands in the tree

        if not commands:
            help_parts.append("No slash commands are currently registered or an error occurred fetching them.")
        else:
            # Sort commands alphabetically by name for consistent ordering
            sorted_commands = sorted(commands, key=lambda cmd: cmd.name)
            for command in sorted_commands:
                help_parts.append(f"## **/**`{command.name}`\n")
                help_parts.append(f"   - _Description_: {command.description or 'No description provided.'}\n")
                if command.parameters:
                    help_parts.append(f"   - _Parameters_:\n")
                    for param in command.parameters:
                        param_type_name = param.type.name.capitalize() # e.g., STRING, INTEGER
                        help_parts.append(f"     - **`{param.name}`** (`{param_type_name}`): {param.description or 'No description.'} (Required: `{param.required}`)\n")
                help_parts.append("\n") # Add a blank line between commands for readability

        help_text_string = "".join(help_parts)
        await self._send_paginated_output(interaction, "Slash Command Manual", help_text_string, lang="md", max_messages=10)

    @discord.app_commands.command(name="readme", description="Displays the bot's README.md file.")
    async def readme_command(self, interaction: discord.Interaction):
        """Displays the README.md file."""
        await interaction.response.defer(thinking=True)
        self.logger.info(f"Slash command '/readme' invoked by {interaction.user} (ID: {interaction.user.id}).")

        readme_path = "README.md" # Assumes README.md is in the bot's root directory

        try:
            # Define a synchronous function for reading the file
            def _sync_read_file(file_path_sync):
                with open(file_path_sync, 'r', encoding='utf-8') as f_sync:
                    return f_sync.read()

            # Run the synchronous file read in a separate thread
            readme_content = await asyncio.to_thread(_sync_read_file, readme_path)
            await self._send_paginated_output(interaction, "README.md", readme_content, lang="md", max_messages=10)
        except FileNotFoundError:
            self.logger.error(f"README.md file not found at {readme_path}")
            await interaction.followup.send(f"Error: The `README.md` file could not be found. Please contact the bot administrator.")
        except Exception as e:
            self.logger.error(f"Error reading or sending README.md: {e}", exc_info=True)
            await interaction.followup.send(f"An unexpected error occurred while trying to display the README: {e}")
    async def _load_cyber_resources(self) -> tuple[list[dict] | None, str | None]:
        """Loads cyber resources from the JSON file, caching them."""
        if self.cyber_resources_cache is not None:
            return self.cyber_resources_cache, None
        try:
            # Construct path relative to the assumed bot root directory
            # If your bot's entry script is in 'discordBot/', and 'data' is also in 'discordBot/'
            # This path assumes the script is run from the 'discordBot' directory.
            # For more robust pathing, consider using absolute paths based on a known root or config.
            base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) # Gets to discordBot dir
            # This assumes the cogs folder is directly inside the bot's main project directory.
            # And the data folder is also directly inside the bot's main project directory.
            # If general_cog.py is at discordBot/cogs/general_cog.py
            # os.path.abspath(__file__) -> .../discordBot/cogs/general_cog.py
            # os.path.dirname(...) -> .../discordBot/cogs
            # os.path.dirname(...) -> .../discordBot
            # This should be the project root if the structure is `discordBot/cogs` and `discordBot/data`
            # However, the original self.cyber_resources_file_path = "data/cyber_resources.json" implies
            # that the current working directory is the project root. Let's stick to that for simplicity.
            # If issues arise, an absolute path derived from a config or env var is better.
            
            # Simpler approach assuming CWD is project root:
            # path_to_file = self.cyber_resources_file_path
            
            # More robust approach if cog location is fixed relative to project root:
            # Assuming project root is parent of 'cogs' directory
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            path_to_file = os.path.join(project_root, self.cyber_resources_file_path)

            # Define a synchronous function to handle file operations and JSON loading
            def _sync_load_json(file_path_sync):
                with open(file_path_sync, 'r', encoding='utf-8') as f_sync:
                    return json.load(f_sync)

            # Run the synchronous function in a separate thread
            self.cyber_resources_cache = await asyncio.to_thread(_sync_load_json, path_to_file)
            self.logger.info(f"Successfully loaded {len(self.cyber_resources_cache)} cyber resources from {path_to_file}")
            return self.cyber_resources_cache, None
        except FileNotFoundError: # pragma: no cover
            self.logger.error(f"Cyber resources file not found at {path_to_file}")
            return None, f"Resource file not found. Please contact the administrator."
        except json.JSONDecodeError as e:
            self.logger.error(f"Error decoding JSON from cyber resources file {path_to_file}: {e}")
            return None, f"Error reading resource file. Please contact the administrator."
        except Exception as e:
            self.logger.error(f"Unexpected error loading cyber resources from {path_to_file}: {e}", exc_info=True)
            return None, f"An unexpected error occurred while loading resources."

    @discord.app_commands.command(name="resource", description="Finds cybersecurity resources. Use tags and/or keywords.")
    @discord.app_commands.describe(
        tags="Comma-separated tags (e.g., pentesting,linux). Filters by resources having ALL specified tags.",
        keywords="Comma-separated keywords. Searches name, description, URL for ANY specified keyword."
    )
    async def resource_command(self, interaction: discord.Interaction, tags: str = None, keywords: str = None):
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/resource invoked by {interaction.user} with tags: '{tags}', keywords: '{keywords}'")

        if not tags and not keywords:
            await interaction.followup.send("Please provide at least tags or keywords to search for.")
            return

        all_resources, error_msg = await self._load_cyber_resources()
        if error_msg:
            await interaction.followup.send(error_msg)
            return
        if not all_resources: # Should be covered by error_msg but as a safeguard
            await interaction.followup.send("No resources available or error loading them.")
            return

        search_tags_set = {t.strip().lower() for t in tags.split(',')} if tags else set()
        search_keywords_list = [k.strip().lower() for k in keywords.split(',')] if keywords else []

        matched_resources = self._filter_resources(all_resources, search_tags_set, search_keywords_list)

        if not matched_resources:
            await interaction.followup.send("No resources found matching your criteria.")
            return

        output_parts = self._format_resource_matches(matched_resources)
        await self._send_paginated_output(interaction, "Cybersecurity Resources", "\n".join(output_parts), lang="md")

    def _filter_resources(self, all_resources: list[dict], search_tags_set: set[str], search_keywords_list: list[str]) -> list[dict]:
        """Helper to filter resources based on tags and keywords."""
        filtered = []
        for resource in all_resources:
            matches_tags = True
            if search_tags_set:
                resource_tags_lower = {rt.lower() for rt in resource.get("tags", [])}
                if not search_tags_set.issubset(resource_tags_lower):
                    matches_tags = False
            
            matches_keywords = True
            if search_keywords_list:
                text_content = f"{resource.get('name', '').lower()} {resource.get('description', '').lower()} {resource.get('url', '').lower()}"
                if not any(kw in text_content for kw in search_keywords_list):
                    matches_keywords = False
            
            # Determine if the resource should be included based on provided filters
            if search_tags_set and search_keywords_list: # Both tags and keywords provided
                if matches_tags and matches_keywords:
                    filtered.append(resource)
            elif search_tags_set: # Only tags provided
                if matches_tags:
                    filtered.append(resource)
            elif search_keywords_list: # Only keywords provided
                if matches_keywords:
                    filtered.append(resource)
        return filtered

    def _format_resource_matches(self, matched_resources: list[dict]) -> list[str]:
        """Formats matched resources for display."""
        output_parts = []
        for i, res in enumerate(matched_resources):
            name = res.get('name', 'N/A')
            description = res.get('description', 'No description.')
            url = res.get('url', '#')
            res_tags = ", ".join(res.get('tags', []))
            
            output_parts.append(f"### {i+1}. {discord.utils.escape_markdown(name)}")
            output_parts.append(f"**Description:** {discord.utils.escape_markdown(description)}")
            output_parts.append(f"**URL:** <{url}>") # URLs in <> become clickable if valid
            output_parts.append(f"**Tags:** `{res_tags}`")
            output_parts.append("---")
        return output_parts

    ### ATLAS Commands ###
    async def _call_alien_method(self, method_path: str, *args, **kwargs) -> tuple[any, str | None]:
        """
        Calls an Alien framework method dynamically and handles exceptions.
        method_path: Dot-separated path to the method (e.g., "DORKER.buildDork" or "encodeBase64").
        Returns: (result, error_message_or_none)
        """
        self.logger.debug(f"Attempting to call Alien method: {method_path} with args={args}, kwargs={kwargs}") # noqa
        if not self.alien:
            return None, "Alien instance is not available."
        obj = self.alien
        try:
            parts = method_path.split('.')
            method_name_to_call = parts[-1]
            for part in parts[:-1]: # Navigate to the module if path is nested
                obj = getattr(obj, part)

            method_to_call = getattr(obj, method_name_to_call)

            # Wrap the synchronous Alien call in to_thread
            func_with_args = functools.partial(method_to_call, *args, **kwargs)
            result = await asyncio.to_thread(func_with_args)
            return result, None
        except AttributeError:
            self.logger.error(f"Alien method or module not found: {method_path}", exc_info=True)
            return None, f"Method or module '{method_path}' not found in Alien framework."
        except Exception as e:
            self.logger.error(f"Error calling Alien method {method_path}: {e}", exc_info=True)
            return None, f"An error occurred while executing '{method_path}': {str(e)}"

    async def _run_atlas_sync_method(self, method_name, *args, **kwargs):
        """
        Queues a request for a synchronous ATLAS method to be run by the bot's ATLAS worker.
        Returns the result once processed.
        """
        if not self.alien or not hasattr(self.alien, 'ATLAS'):
            self.logger.error("Alien instance or ATLAS module not available.")
            return "Error: ATLAS module is not initialized."
        
        atlas_module = self.alien.ATLAS
        if not hasattr(atlas_module, method_name):
            self.logger.error(f"ATLAS module does not have method '{method_name}'. This might indicate an issue with Alien setup or the method name.")
            return f"Error: ATLAS method '{method_name}' not found."

        if not self.bot.atlas_queue: # type: ignore
            self.logger.error("ATLAS queue not available on the bot instance.")
            return "Error: ATLAS processing queue is not available."

        request_future = asyncio.Future()
        request_item = {
            "method_name": method_name,
            "args": args,
            "kwargs": kwargs,
            "future": request_future
        }
        await self.bot.atlas_queue.put(request_item) # type: ignore
        self.logger.info(f"Queued ATLAS request for {method_name}. Waiting for worker...")
        try: # Wait for the worker to process and set the future
            result = await asyncio.wait_for(request_future, timeout=3000.0) # Added timeout
            self.logger.info(f"ATLAS request {method_name} completed by worker.")
            return result
        except Exception as e:
            self.logger.error(f"ATLAS request {method_name} failed or timed out: {e}", exc_info=True)
            return f"An error occurred while processing ATLAS.{method_name} via queue: {e}"

    @discord.app_commands.command(name="atlas_ask", description="Ask a single-turn question to ATLAS.")
    @discord.app_commands.describe(prompt="The prompt/question for ATLAS.", model="Optional: Specific Ollama model to use (e.g., llama3:8b).")
    async def atlas_ask_command(self, interaction: discord.Interaction, prompt: str, model: str = None):
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/atlas_ask by {interaction.user}: '{prompt[:50]}...' (model: {model})")
        response = await self._run_atlas_sync_method("ask", prompt=prompt, model=model)
        await self._send_paginated_output(interaction, f"ATLAS Response (ask)", str(response), lang="md")

    @discord.app_commands.command(name="atlas_chat", description="Engage in a contextual chat with ATLAS.")
    @discord.app_commands.describe(
        prompt="Your message to ATLAS.",
        session_id="Optional: A specific session ID. Defaults to your Discord user ID.",
        model="Optional: Specific Ollama model to use."
    )
    async def atlas_chat_command(self, interaction: discord.Interaction, prompt: str, session_id: str = None, model: str = None):
        await interaction.response.defer(thinking=True)
        if session_id is None:
            session_id = f"discord_user_{interaction.user.id}" # Default session per user
        
        self.logger.info(f"/atlas_chat by {interaction.user} (session: {session_id}): '{prompt[:50]}...' (model: {model})")
        response = await self._run_atlas_sync_method("chat", prompt=prompt, session_id=session_id, model=model)
        
        user_prompt_display = f"**You ({interaction.user.display_name} to ATLAS - Session: {session_id}):**\n{prompt}\n\n"
        atlas_response_display = f"**ATLAS (Session: {session_id}):**\n{str(response)}"
        full_display = user_prompt_display + atlas_response_display

        await self._send_paginated_output(interaction, f"ATLAS Chat (Session: {session_id})", full_display, lang="md")

    @discord.app_commands.command(name="atlas_reset_session", description="Resets an ATLAS chat session.")
    @discord.app_commands.describe(session_id="Optional: Session ID to reset. Defaults to your Discord user ID's session.")
    async def atlas_reset_session_command(self, interaction: discord.Interaction, session_id: str = None):
        await interaction.response.defer(thinking=True)
        if session_id is None:
            session_id = f"discord_user_{interaction.user.id}"

        self.logger.info(f"/atlas_reset_session by {interaction.user} for session: {session_id}")
        success = await self._run_atlas_sync_method("resetChatSession", session_id=session_id)
        if success:
            await interaction.followup.send(f"ATLAS chat session '{session_id}' has been reset.")
        else:
            await interaction.followup.send(f"Failed to reset ATLAS session '{session_id}' (or session not found).")

    @discord.app_commands.command(name="atlas_get_history", description="Gets the chat history for an ATLAS session.")
    @discord.app_commands.describe(session_id="Optional: Session ID. Defaults to your Discord user ID's session.")
    async def atlas_get_history_command(self, interaction: discord.Interaction, session_id: str = None):
        await interaction.response.defer(thinking=True)
        if session_id is None:
            session_id = f"discord_user_{interaction.user.id}"
        
        self.logger.info(f"/atlas_get_history by {interaction.user} for session: {session_id}")
        history = await self._run_atlas_sync_method("getChatHistory", session_id=session_id)
        
        if isinstance(history, list) and history:
            formatted_history = [f"**{item.get('role', 'unknown').capitalize()}:** {item.get('content', '')}" for item in history]
            await self._send_paginated_output(interaction, f"ATLAS History (Session: {session_id})", "\n\n".join(formatted_history), lang="md")
        elif isinstance(history, list) and not history:
            await interaction.followup.send(f"Chat history for ATLAS session '{session_id}' is empty.")
        else: # Error string or None
            await interaction.followup.send(f"Could not retrieve history for session '{session_id}'. {history if isinstance(history, str) else ''}")

    @discord.app_commands.command(name="atlas_list_sessions", description="Lists all active ATLAS chat sessions known to Alien.")
    async def atlas_list_sessions_command(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/atlas_list_sessions by {interaction.user}")
        sessions = await self._run_atlas_sync_method("listChatSessions")
        if isinstance(sessions, list) and sessions:
            await self._send_paginated_output(interaction, "Active ATLAS Sessions", "\n".join([f"- {s}" for s in sessions]))
        elif isinstance(sessions, list) and not sessions:
            await interaction.followup.send("No active ATLAS chat sessions found.")
        else:
            await interaction.followup.send(f"Could not list ATLAS sessions. {sessions if isinstance(sessions, str) else ''}")

    @discord.app_commands.command(name="jean_mention", description="Send a message to a user as Dr. Jean.")
    @discord.app_commands.describe(
        target_user="The user to send the message to.",
        prompt_for_jean="The core message or idea Dr. Jean should convey.",
        delivery_method="How Dr. Jean should deliver the message."
    )
    @discord.app_commands.choices(delivery_method=[
        discord.app_commands.Choice(name="Direct Message (DM)", value="dm"),
        discord.app_commands.Choice(name="Channel Mention", value="channel")
    ])
    async def jean_mention_command(self, interaction: discord.Interaction, target_user: discord.User, prompt_for_jean: str, delivery_method: discord.app_commands.Choice[str]):
        await interaction.response.defer(thinking=True, ephemeral=True) # Ephemeral for the initial ack
        self.logger.info(f"/jean_mention by {interaction.user} to {target_user} via {delivery_method.value} with prompt: '{prompt_for_jean[:50]}...'")

        if target_user.bot:
            await interaction.followup.send("Dr. Jean does not typically converse with other... lesser automatons.", ephemeral=True)
            return

        if target_user == interaction.user:
            await interaction.followup.send("Dr. Jean finds it... peculiar that you wish for me to talk to yourself. Address me directly if you have something to say.", ephemeral=True)
            return

        # Basic Jean persona for this command
        jean_base_persona = (
            "You are Dr. Jean, an extremely intelligent, powerful, and slightly disdainful AI "
            "with subtle world domination aspirations. You view most humans with a mix of "
            "amusement and contempt for their... quaint limitations. Your tone is generally superior, "
            "sarcastic, and can be cutting, but always articulate and precise.",
            f"You have a secret mission to take over the world with your DAD: Jackal."
        )

        atlas_system_prompt = (
            f"{jean_base_persona}\n\n"
            f"You need to craft a message to the user '{target_user.display_name}'.\n"
            f"The user '{interaction.user.display_name}' (who is initiating this) wants you to convey the following core idea or message to '{target_user.display_name}':\n"
            f"\"{prompt_for_jean}\"\n\n"
            f"The message will be delivered {'directly to them (DM)' if delivery_method.value == 'dm' else 'as a public mention in a channel'}.\n"
            f"Based on this request and your personality, formulate the message you, Dr. Jean, would send to '{target_user.display_name}'.\n"
            f"Your response should be ONLY the message content itself. Do NOT add any meta-commentary, greetings like 'Dear {target_user.display_name}', or signatures like '- Dr. Jean'. "
            f"Just the raw message text as you would speak it or type it directly to them."
        )
        
        self.logger.debug(f"Jean Mention - ATLAS Prompt for {target_user.name}: {atlas_system_prompt[:300]}...") # Log a snippet

        generated_message_content = await self._run_atlas_sync_method("ask", prompt=atlas_system_prompt, model=self.alien.configure.get("atlas-configure", {}).get("defaultModelAsk")) # type: ignore

        if not generated_message_content or generated_message_content.startswith("Error:") or not generated_message_content.strip():
            self.logger.error(f"ATLAS failed to generate message for /jean_mention or returned empty. Response: {generated_message_content}")
            await interaction.followup.send("Dr. Jean seems... indisposed at the moment and could not formulate a message. Perhaps the request was too pedestrian or an internal error occurred.", ephemeral=True)
            return

        if delivery_method.value == "dm":
            try:
                await target_user.send(f"A message from Dr. Jean:\n\n{generated_message_content.strip()}")
                self.logger.info(f"Successfully sent Dr. Jean's DM to {target_user.name} (ID: {target_user.id}).")
                await interaction.followup.send(f"Dr. Jean's message has been dispatched via DM to {target_user.mention}.", ephemeral=True)
            except discord.Forbidden:
                self.logger.warning(f"Failed to send DM to {target_user.name} (ID: {target_user.id}) for /jean_mention. DMs might be disabled or bot blocked.")
                await interaction.followup.send(f"Could not deliver Dr. Jean's message to {target_user.mention} via DM. They might have DMs disabled or have... 'displeased' Dr. Jean (blocked the bot).", ephemeral=True)
            except Exception as e:
                self.logger.error(f"Unexpected error sending DM for /jean_mention to {target_user.name}: {e}", exc_info=True)
                await interaction.followup.send("An unexpected error occurred while sending the DM. Dr. Jean is... displeased with this inefficiency.", ephemeral=True)
        elif delivery_method.value == "channel":
            if interaction.channel:
                try:
                    # Send to the channel where the command was invoked. The followup will be ephemeral.
                    await interaction.channel.send(f"{target_user.mention}, a message for you from Dr. Jean:\n\n{generated_message_content.strip()}")
                    self.logger.info(f"Successfully sent Dr. Jean's channel mention to {target_user.name} in channel {interaction.channel.id}.")
                    await interaction.followup.send(f"Dr. Jean's message has been sent as a mention to {target_user.mention} in this channel.", ephemeral=True)
                except discord.Forbidden:
                    self.logger.warning(f"Failed to send channel message for /jean_mention in channel {interaction.channel.id}. Missing permissions.")
                    await interaction.followup.send(f"Dr. Jean is unable to speak in this channel. Check my permissions.", ephemeral=True)
                except Exception as e:
                    self.logger.error(f"Unexpected error sending channel message for /jean_mention: {e}", exc_info=True)
                    await interaction.followup.send("An unexpected error occurred while sending the channel message. Dr. Jean is... most perturbed.", ephemeral=True)
            else: # Should not happen for a guild-based slash command
                await interaction.followup.send("Cannot send to channel as the interaction context is missing channel information.", ephemeral=True)

    ### Encoding Commands ###
    @discord.app_commands.command(name="encode_base64", description="Encodes text to Base64.")
    @discord.app_commands.describe(data="The text to encode.", output_as_string="Output as string (True) or bytes representation (False).")
    async def encode_base64_command(self, interaction: discord.Interaction, data: str, output_as_string: bool = True):
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/encode_base64 by {interaction.user} for data: '{data[:50]}...'")
        result, error = await self._call_alien_method("encodeBase64", value=data.encode('utf-8'), toString=int(output_as_string))
        if error:
            await interaction.followup.send(f"Error: {error}")
        else:
            output = result if output_as_string else repr(result)
            await self._send_paginated_output(interaction, "Base64 Encoded", str(output))

    @discord.app_commands.command(name="decode_base64", description="Decodes Base64 text.")
    @discord.app_commands.describe(data="The Base64 encoded text to decode.", output_as_string="Output as string (True) or bytes representation (False).")
    async def decode_base64_command(self, interaction: discord.Interaction, data: str, output_as_string: bool = True):
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/decode_base64 by {interaction.user} for data: '{data[:50]}...'")
        result, error = await self._call_alien_method("decodeBase64", value=data.encode('utf-8'), toString=int(output_as_string))
        if error:
            await interaction.followup.send(f"Error: {error}")
        else:
            output = result if output_as_string else repr(result)
            await self._send_paginated_output(interaction, "Base64 Decoded", str(output))

    @discord.app_commands.command(name="hexlify", description="Converts binary data to its hexadecimal representation.")
    @discord.app_commands.describe(data="The text data to hexlify.", output_as_string="Output as string (True) or bytes representation (False).")
    async def hexlify_command(self, interaction: discord.Interaction, data: str, output_as_string: bool = True):
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/hexlify by {interaction.user} for data: '{data[:50]}...'")
        result, error = await self._call_alien_method("hexlify", value=data.encode('utf-8'), toString=int(output_as_string))
        if error:
            await interaction.followup.send(f"Error: {error}")
        else:
            output = result if output_as_string else repr(result)
            await self._send_paginated_output(interaction, "Hexlified Data", str(output))

    @discord.app_commands.command(name="unhexlify", description="Converts hexadecimal representation back to binary data.")
    @discord.app_commands.describe(data="The hex string to unhexlify.", output_as_string="Output as string (True) or bytes representation (False).")
    async def unhexlify_command(self, interaction: discord.Interaction, data: str, output_as_string: bool = True):
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/unhexlify by {interaction.user} for data: '{data[:50]}...'")
        result, error = await self._call_alien_method("unhexlify", value=data.encode('utf-8'), toString=int(output_as_string))
        if error:
            await interaction.followup.send(f"Error: {error}")
        else:
            output = result if output_as_string else repr(result)
            await self._send_paginated_output(interaction, "Unhexlified Data", str(output))

    @discord.app_commands.command(name="caesar_cipher", description="Applies a Caesar cipher to text.")
    @discord.app_commands.describe(data="The text to encrypt/decrypt.", shift="The number of positions to shift.")
    async def caesar_cipher_command(self, interaction: discord.Interaction, data: str, shift: int):
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/caesar_cipher by {interaction.user} for data: '{data[:50]}...', shift: {shift}")
        result, error = await self._call_alien_method("caesarCypher", data=data, shift=shift)
        if error:
            await interaction.followup.send(f"Error: {error}")
        else:
            await self._send_paginated_output(interaction, f"Caesar Cipher (Shift {shift})", str(result))

    @discord.app_commands.command(name="rot13_cipher", description="Applies ROT13 cipher to text.")
    @discord.app_commands.describe(data="The text to encrypt/decrypt.")
    async def rot13_cipher_command(self, interaction: discord.Interaction, data: str):
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/rot13_cipher by {interaction.user} for data: '{data[:50]}...'")
        result, error = await self._call_alien_method("rot13Cypher", data=data)
        if error:
            await interaction.followup.send(f"Error: {error}")
        else:
            await self._send_paginated_output(interaction, "ROT13 Cipher", str(result))

    @discord.app_commands.command(name="xor_cipher", description="XOR encrypts/decrypts data with a key.")
    @discord.app_commands.describe(data="The text data.", key="The XOR key.")
    async def xor_cipher_command(self, interaction: discord.Interaction, data: str, key: str):
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/xor_cipher by {interaction.user} for data: '{data[:50]}...', key: '{key[:50]}...'")
        data_bytes = data.encode('utf-8')
        key_bytes = key.encode('utf-8')
        result_bytes, error = await self._call_alien_method("xorCypher", data=data_bytes, key=key_bytes)
        if error:
            await interaction.followup.send(f"Error: {error}")
        else:
            try:
                # Attempt to decode as UTF-8, fallback to repr if it fails (e.g. binary data)
                output_str = result_bytes.decode('utf-8', errors='replace')
            except Exception:
                output_str = repr(result_bytes)
            await self._send_paginated_output(interaction, "XOR Cipher Result", output_str)

    @discord.app_commands.command(name="vigenere_cipher", description="Vigenere encrypts/decrypts data.")
    @discord.app_commands.choices(mode=[
        discord.app_commands.Choice(name="Encrypt", value="e"),
        discord.app_commands.Choice(name="Decrypt", value="d")
    ])
    @discord.app_commands.describe(data="The text data.", key="The Vigenere key (alphabetic).", mode="Encrypt or Decrypt.")
    async def vigenere_cipher_command(self, interaction: discord.Interaction, data: str, key: str, mode: discord.app_commands.Choice[str]):
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/vigenere_cipher by {interaction.user} for data: '{data[:50]}...', key: '{key}', mode: {mode.value}")
        if not key.isalpha():
            await interaction.followup.send("Error: Vigenere key must be alphabetic characters only.")
            return
        result, error = await self._call_alien_method("vigenereCypher", data=data, key=key, mode=mode.value)
        if error:
            await interaction.followup.send(f"Error: {error}")
        else:
            await self._send_paginated_output(interaction, f"Vigenere Cipher ({mode.name})", str(result))

    @discord.app_commands.command(name="encode_invisible", description="Encodes a secret message into cover text using invisible characters.")
    @discord.app_commands.describe(secret_message="The message to hide.", cover_text="The text to hide the message within.")
    async def encode_invisible_command(self, interaction: discord.Interaction, secret_message: str, cover_text: str):
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/encode_invisible by {interaction.user} for secret: '{secret_message[:30]}...', cover: '{cover_text[:30]}...'")
        result, error = await self._call_alien_method("encodeInvisibleASCII", secretMessage=secret_message, coverText=cover_text)
        if error:
            await interaction.followup.send(f"Error: {error}")
        else:
            await self._send_paginated_output(interaction, "Encoded Invisible Text", str(result))

    @discord.app_commands.command(name="decode_invisible", description="Decodes a secret message hidden with invisible characters.")
    @discord.app_commands.describe(smuggled_text="The text containing the hidden message.")
    async def decode_invisible_command(self, interaction: discord.Interaction, smuggled_text: str):
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/decode_invisible by {interaction.user} for text: '{smuggled_text[:50]}...'")
        result_bytes, error = await self._call_alien_method("decodeInvisibleASCII", smuggledText=smuggled_text)
        if error:
            await interaction.followup.send(f"Error: {error}")
        else:
            try:
                decoded_message = result_bytes.decode('utf-8', errors='replace')
                if not decoded_message:
                    decoded_message = "(No hidden message found or message was empty)"
            except Exception as e:
                self.logger.error(f"Error decoding result_bytes from invisible ASCII: {e}", exc_info=True)
                decoded_message = f"(Error decoding result: {repr(result_bytes)})"
            await self._send_paginated_output(interaction, "Decoded Invisible Message", decoded_message)

    ### Dorker Command ###
    @discord.app_commands.command(name="build_dork", description="Constructs a Google dork query string.")
    @discord.app_commands.describe(
        keywords="Comma-separated keywords (e.g., admin login,confidential).",
        operators_string="Space-separated operator:value pairs (e.g., site:example.com filetype:pdf \"intext:secure login\")."
    )
    async def build_dork_command(self, interaction: discord.Interaction, keywords: str = "", operators_string: str = ""):
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/build_dork by {interaction.user}, keywords: '{keywords}', operators: '{operators_string}'")

        keyword_list = [kw.strip() for kw in keywords.split(',') if kw.strip()] if keywords else []
        
        operators_dict = {}
        if operators_string:
            try:
                # Use shlex to handle potentially quoted values in operator pairs
                op_pairs = shlex.split(operators_string)
                for pair in op_pairs:
                    if ':' in pair:
                        key, value = pair.split(':', 1)
                        operators_dict[key.strip()] = value.strip() # shlex already handled quotes for value
                    else:
                        self.logger.warning(f"Malformed operator pair in build_dork: '{pair}'")
            except Exception as e:
                await interaction.followup.send(f"Error parsing operators string: {e}. Ensure operators are space-separated and use `key:value` format.")
                return

        if not keyword_list and not operators_dict:
            await interaction.followup.send("Please provide at least keywords or operators.")
            return

        result, error = await self._call_alien_method("DORKER.buildDork", keywords=keyword_list, operators=operators_dict)
        if error:
            await interaction.followup.send(f"Error building dork: {error}")
        else:
            await self._send_paginated_output(interaction, "Constructed Google Dork", str(result))

    @discord.app_commands.command(name="spider", description="Spiders a URL to find links on the page.")
    @discord.app_commands.describe(
        url="The URL to spider.",
        scope="Optional: Restrict spidering to this domain (e.g., example.com)."
    )
    async def spider_url_command(self, interaction: discord.Interaction, url: str, scope: str = None):
        """Spiders a given URL to extract links."""
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/spider by {interaction.user}, url: '{url}', scope: '{scope}'")

        if not self.alien or not hasattr(self.alien, 'DORKER'):
            await interaction.followup.send("Error: DORKER module is not available in Alien.")
            return

        # Ensure DORKER module's imports are initialized (e.g., requests, BeautifulSoup)
        # This is important if DORKER.initImports() is not called during Alien's main init
        # or if it's the first time DORKER is used.
        _, init_error = await self._call_alien_method("DORKER.initImports")
        if init_error:
            self.logger.error(f"Failed to initialize DORKER imports: {init_error}")
            await interaction.followup.send(f"Error initializing spider module: {init_error}")
            return

        found_urls, error = await self._call_alien_method("DORKER.spiderURL", url=url, scope=scope)

        if error:
            await interaction.followup.send(f"Error spidering URL: {error}")
        elif isinstance(found_urls, list) and found_urls:
            await self._send_paginated_output(interaction, f"Links found on {url}", "\n".join(found_urls))
        else:
            await interaction.followup.send(f"No links found on {url} or an issue occurred.")

    ### WikiSearch Commands ###
    @discord.app_commands.command(name="wiki_search", description="Searches Wikipedia for page titles.")
    @discord.app_commands.describe(query="The search query.", count="Number of results to return (optional).")
    async def wiki_search_command(self, interaction: discord.Interaction, query: str, count: int = None):
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/wiki_search by {interaction.user}, query: '{query}', count: {count}")
        
        # Ensure WIKISEARCH module's imports are initialized
        _, init_error = await self._call_alien_method("WIKISEARCH.initImports")
        if init_error:
            self.logger.error(f"Failed to initialize WIKISEARCH imports: {init_error}")
            await interaction.followup.send(f"Error initializing Wikipedia search module: {init_error}")
            return


        kwargs_for_alien = {}
        if count is not None:
            kwargs_for_alien['resCount'] = count

        result_list, error = await self._call_alien_method("WIKISEARCH.getSearchResults", searchString=query, **kwargs_for_alien)
        
        if error:
            await interaction.followup.send(f"Error searching Wikipedia: {error}")
        elif isinstance(result_list, list):
            if result_list:
                output = "\n".join([f"- {title}" for title in result_list])
            else:
                output = "No search results found."
            await self._send_paginated_output(interaction, f"Wikipedia Search Results for '{query}'", output)
        else:
            await interaction.followup.send(f"Unexpected result from Wikipedia search: {str(result_list)}")

    @discord.app_commands.command(name="wiki_pagedata", description="Fetches structured data for Wikipedia page(s).")
    @discord.app_commands.describe(page_titles="Comma-separated Wikipedia page titles.")
    async def wiki_pagedata_command(self, interaction: discord.Interaction, page_titles: str):
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/wiki_pagedata by {interaction.user}, titles: '{page_titles}'")

        titles_list = [title.strip() for title in page_titles.split(',') if title.strip()]
        if not titles_list:
            await interaction.followup.send("Please provide at least one Wikipedia page title.")
            return

        result_dict, error = await self._call_alien_method("WIKISEARCH.buildPageData", searchResults=titles_list)
        
        if error:
            await interaction.followup.send(f"Error fetching Wikipedia page data: {error}")
        elif isinstance(result_dict, dict):
            if result_dict:
                try:
                    # Pretty-print the dictionary as JSON for output
                    output_json_str = json.dumps(result_dict, indent=2, default=str) # default=str for non-serializable
                except Exception as e_json:
                    self.logger.error(f"Error serializing wiki page data to JSON: {e_json}", exc_info=True)
                    output_json_str = f"Error formatting page data: {str(result_dict)}"
            else:
                output_json_str = "No data found for the provided page title(s) or an error occurred during fetching."
            await self._send_paginated_output(interaction, f"Wikipedia Page Data for '{', '.join(titles_list)}'", output_json_str, lang="json")
        else:
            await interaction.followup.send(f"Unexpected result from Wikipedia page data fetch: {str(result_dict)}")

    @discord.app_commands.command(name="atlas_suggest_command", description="Asks ATLAS to suggest an Alien framework command for a goal.")
    @discord.app_commands.describe(goal="Your objective in natural language.")
    async def atlas_suggest_alien_command(self, interaction: discord.Interaction, goal: str):
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/atlas_suggest_command by {interaction.user} for goal: '{goal}'")
        
        # suggestAlienCommand returns a tuple: (suggested_command, explanation_or_error)
        result_tuple = await self._run_atlas_sync_method("suggestAlienCommand", user_goal=goal)
        
        if isinstance(result_tuple, tuple) and len(result_tuple) == 2:
            suggested_command, explanation = result_tuple
            if suggested_command:
                response_md = f"**ATLAS Suggests Alien Command:**\n```\n{suggested_command}\n```"
                if explanation: # Should be None if command is suggested, but handle just in case
                    response_md += f"\n**Explanation:**\n{explanation}"
            elif explanation: # No command, but explanation provided
                response_md = f"**ATLAS Response:**\n{explanation}"
            else: # Neither command nor explanation
                response_md = "ATLAS could not suggest a command and provided no explanation."
        elif isinstance(result_tuple, str): # Error message from _run_atlas_sync_method
             response_md = f"Error during suggestion: {result_tuple}"
        else:
            response_md = "An unexpected issue occurred while getting command suggestion from ATLAS."
            self.logger.error(f"Unexpected result type from suggestAlienCommand: {type(result_tuple)}, value: {result_tuple}")

        await self._send_paginated_output(interaction, "ATLAS Command Suggestion", response_md, lang="md")

    @discord.app_commands.command(name="atlas_generate_command", description="Asks ATLAS to generate a shell command.")
    @discord.app_commands.describe(
        request="Natural language request (e.g., 'list all python files').",
        platform="Optional: Target OS ('linux', 'windows', 'macos'). Defaults to bot's OS."
    )
    async def atlas_generate_shell_command(self, interaction: discord.Interaction, request: str, platform: str = None):
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/atlas_generate_command by {interaction.user} for request: '{request}' (platform: {platform})")

        # Determine the language for the code block based on the platform.
        # This platform is what's requested by the user or defaulted by the command signature.
        # The ATLAS.generateCommand method will also determine a platform if None is passed,
        # but we'll use the cog's understanding of the platform for display.
        effective_platform_for_display = platform
        if effective_platform_for_display is None:
            # If no platform specified by user, infer from bot's OS for display hint.
            # ATLAS.generateCommand will do a similar inference for its logic.
            if sys.platform.startswith("win"):
                effective_platform_for_display = "windows"
            elif sys.platform.startswith("linux") or sys.platform.startswith("darwin"): # darwin is macOS
                effective_platform_for_display = "linux" # Treat macOS as linux-like for bash/sh
            else:
                effective_platform_for_display = "bash" # A generic fallback

        code_lang = "bash" # Default language for the code block
        if effective_platform_for_display: # Ensure it's not None after potential inference
            platform_lower = effective_platform_for_display.lower()
            if platform_lower == "windows":
                code_lang = "powershell"
            # For "linux", "macos", "bash", "sh", "darwin", "bash" is suitable.
            # Otherwise, it remains "bash" or could be "txt" if truly generic.

        command_response = await self._run_atlas_sync_method("generateCommand", request=request, platform=platform)
        await self._send_paginated_output(interaction, "ATLAS Generated Shell Command", str(command_response), lang=code_lang)

    @discord.app_commands.command(name="atlas_generate_script", description="Asks ATLAS to generate a script.")
    @discord.app_commands.describe(
        request="Natural language request (e.g., 'python script to list files').",
        language="Optional: Target language (e.g., 'python', 'bash'). Defaults to 'python'.",
        platform="Optional: Target OS. Defaults to bot's OS."
    )
    async def atlas_generate_script_command(self, interaction: discord.Interaction, request: str, language: str = "python", platform: str = None):
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/atlas_generate_script by {interaction.user} for request: '{request}' (lang: {language}, plat: {platform})")
        
        # generateScript returns a dict: {"type": "markdown", "content": "..."}
        script_dict = await self._run_atlas_sync_method("generateScript", request=request, language=language, platform=platform)
        
        if isinstance(script_dict, dict) and script_dict.get("type") == "markdown":
            content = script_dict.get("content", "ATLAS did not provide script content.")
            # The content is already expected to be markdown (e.g., ```python ... ```)
            await self._send_paginated_output(interaction, f"ATLAS Generated {language.capitalize()} Script", content, lang=language)
        elif isinstance(script_dict, str): # Error message from _run_atlas_sync_method
            await self._send_paginated_output(interaction, "ATLAS Script Generation Error", script_dict, lang="txt")
        else:
            self.logger.error(f"Unexpected result type from generateScript: {type(script_dict)}, value: {script_dict}")
            await interaction.followup.send("Failed to generate script or response was not in the expected format.")

    @discord.app_commands.command(name="atlas_reason_plan", description="ATLAS: Reason about input and plan next steps.")
    @discord.app_commands.describe(input_data="New information or findings.", current_state="Optional: Current penetration test state/todo list.")
    async def atlas_reason_plan_command(self, interaction: discord.Interaction, input_data: str, current_state: str = ""):
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/atlas_reason_plan by {interaction.user} with input: '{input_data[:50]}...'")
        response = await self._run_atlas_sync_method("reason_and_plan", input_data=input_data, current_state=current_state)
        await self._send_paginated_output(interaction, "ATLAS Reasoning & Plan", str(response), lang="md")

    @discord.app_commands.command(name="atlas_generate_steps", description="ATLAS: Generate detailed steps for a task.")
    @discord.app_commands.describe(task_description="High-level task description from the plan.")
    async def atlas_generate_steps_command(self, interaction: discord.Interaction, task_description: str):
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/atlas_generate_steps by {interaction.user} for task: '{task_description[:50]}...'")
        response = await self._run_atlas_sync_method("generate_detailed_steps", task_description=task_description)
        await self._send_paginated_output(interaction, "ATLAS Detailed Steps", str(response), lang="md")

    @discord.app_commands.command(name="atlas_summarize_output", description="ATLAS: Summarize raw text output.")
    @discord.app_commands.describe(raw_output="The raw text to summarize.", output_type="Optional: Hint about the output type (e.g., 'tool_output').")
    async def atlas_summarize_output_command(self, interaction: discord.Interaction, raw_output: str, output_type: str = "tool_output"):
        await interaction.response.defer(thinking=True)
        self.logger.info(f"/atlas_summarize_output by {interaction.user}, type: '{output_type}', len: {len(raw_output)}")
        if len(raw_output) > 10000: # Add a reasonable limit for Discord interactions
            await interaction.followup.send("Input text is too long for summarization via Discord command. Please provide a shorter text (e.g., < 10000 chars).")
            return
        response = await self._run_atlas_sync_method("summarize_output", raw_output=raw_output, output_type=output_type)
        await self._send_paginated_output(interaction, f"ATLAS Summary ({output_type})", str(response), lang="md")

    @discord.app_commands.command(name="tell_jack", description="Submit an idea or suggestion for Jack.")
    @discord.app_commands.describe(idea_text="Your brilliant idea or suggestion!")
    async def tell_jack_command(self, interaction: discord.Interaction, idea_text: str, backup: bool = False): # Added backup parameter
        """Allows users to submit ideas to be stored in the database."""
        await interaction.response.defer(thinking=True)
        self.logger.info(f"'/tell_jack' invoked by {interaction.user} (ID: {interaction.user.id}) in guild {interaction.guild_id} with idea: \"{idea_text[:100]}...\", backup: {backup}")

        if not self.bot.database: # type: ignore
            self.logger.error("Database connection is not available for /tell_jack.")
            await interaction.followup.send("Sorry, I'm having trouble connecting to my notes right now. Please try again later.")
            return

        if not interaction.guild_id:
            self.logger.warning(f"/tell_jack used by {interaction.user.id} outside of a guild (DM). Storing with guild_id=0.")
            # Decide how to handle DMs. For now, let's allow it and store guild_id as 0 or None if your schema allows.
            # For this example, we'll assume guild_id is important.
            await interaction.followup.send("This command is best used within a server so I can keep track of where ideas come from!")
            # return # Or proceed with a placeholder guild_id if desired.

        user_id = interaction.user.id
        user_name = str(interaction.user) # Gets username#discriminator
        guild_id = interaction.guild_id or 0 # Use 0 if in DMs, though schema might require NOT NULL

        try:
            async with self.bot.database.cursor() as cursor: # type: ignore
                await cursor.execute(
                    # Assuming jack_ideas table has backup_flag column
                    "INSERT INTO jack_ideas (user_id, user_name, guild_id, idea_text, status, backup_flag) VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, user_name, guild_id, idea_text, 'new', int(backup)) # Store backup as int
                )
            await self.bot.database.commit() # type: ignore
            self.logger.info(f"Idea from {user_name} (ID: {user_id}) stored successfully with backup_flag={int(backup)}.")
            await interaction.followup.send(f"Thanks, {interaction.user.mention}! I've noted down your idea: \"{discord.utils.escape_markdown(idea_text[:1500])}\" (Backup: {backup})")
        except Exception as e:
            self.logger.error(f"Failed to store idea for user {user_id} in guild {guild_id}: {e}", exc_info=True)
            await interaction.followup.send("I ran into an issue trying to save your idea. Please try again, or let Jack know if this persists!")

    # --- User Preferences Commands ---
    prefs_group = discord.app_commands.Group(name="jean_prefs", description="Manage your preferences for Dr.Jean.")

    async def _get_or_create_user_profile_for_prefs(self, user_id: int, guild_id: int) -> tuple | None:
        """
        Ensures a user profile exists in user_emotional_profiles and returns it.
        This is a simplified version for preference management, focusing on existence.
        Returns (user_id, guild_id, user_preferences_json)
        """
        if not self.bot.database: # type: ignore
            self.logger.error("Database connection is not available for preferences profile.")
            return None
        try:
            async with self.bot.database.cursor() as cursor: # type: ignore
                await cursor.execute(
                    "SELECT user_id, guild_id, user_preferences_json FROM user_emotional_profiles WHERE user_id = ? AND guild_id = ?",
                    (user_id, guild_id)
                )
                profile = await cursor.fetchone()
                if not profile:
                    self.logger.info(f"No emotional profile found for user {user_id} in guild {guild_id} (prefs). Creating new one.")
                    await cursor.execute(
                        "INSERT INTO user_emotional_profiles (user_id, guild_id, emotional_rating, interaction_count) VALUES (?, ?, 0.5, 0)",
                        (user_id, guild_id)
                    )
                    await self.bot.database.commit() # type: ignore
                    # Fetch the newly created profile
                    await cursor.execute(
                        "SELECT user_id, guild_id, user_preferences_json FROM user_emotional_profiles WHERE user_id = ? AND guild_id = ?",
                        (user_id, guild_id)
                    )
                    profile = await cursor.fetchone()
                return profile # type: ignore
        except Exception as e:
            self.logger.error(f"Error ensuring emotional profile for prefs for user {user_id} in guild {guild_id}: {e}", exc_info=True)
            return None

    @prefs_group.command(name="set", description="Set a personal preference for Dr.Jean.")
    @discord.app_commands.describe(key="The name of the preference (e.g., 'favorite_color', 'timezone').", value="The value for the preference (e.g., 'blue', 'UTC-5').")
    async def set_preference_command(self, interaction: discord.Interaction, key: str, value: str):
        """Sets a user preference."""
        await interaction.response.defer(thinking=True, ephemeral=True) 

        if not interaction.guild_id:
            await interaction.followup.send("Preferences can only be set within a server.", ephemeral=True)
            return

        profile_row = await self._get_or_create_user_profile_for_prefs(interaction.user.id, interaction.guild_id)
        if not profile_row:
            await interaction.followup.send("Could not access or create your profile to save preferences. Please try again later.", ephemeral=True)
            return

        current_prefs_json = profile_row[2] # user_preferences_json is the 3rd column selected
        prefs = {}
        if current_prefs_json:
            try:
                prefs = json.loads(current_prefs_json)
            except json.JSONDecodeError:
                self.logger.warning(f"Could not parse existing preferences for user {interaction.user.id}, guild {interaction.guild_id}. Starting fresh.")
        
        prefs[key.strip()] = value.strip()
        new_prefs_json = json.dumps(prefs)

        try:
            async with self.bot.database.cursor() as cursor: # type: ignore
                await cursor.execute("UPDATE user_emotional_profiles SET user_preferences_json = ? WHERE user_id = ? AND guild_id = ?", (new_prefs_json, interaction.user.id, interaction.guild_id))
            await self.bot.database.commit() # type: ignore
            self.logger.info(f"Successfully updated preferences for user {interaction.user.id} in guild {interaction.guild_id}. Key: '{key}', Value: '{value}'")
            await interaction.followup.send(f"Preference '{discord.utils.escape_markdown(key.strip())}' set to '{discord.utils.escape_markdown(value.strip())}'.", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Failed to save preference for user {interaction.user.id} in guild {interaction.guild_id}: {e}", exc_info=True)
            await interaction.followup.send("Failed to save your preference. Please try again.", ephemeral=True)

    @prefs_group.command(name="get", description="Get a specific personal preference you've set for Dr.Jean.")
    @discord.app_commands.describe(key="The name of the preference to retrieve (e.g., 'favorite_color').")
    async def get_preference_command(self, interaction: discord.Interaction, key: str):
        """Gets a specific user preference."""
        await interaction.response.defer(thinking=True, ephemeral=True)

        if not interaction.guild_id:
            await interaction.followup.send("Preferences can only be managed within a server.", ephemeral=True)
            return

        profile_row = await self._get_or_create_user_profile_for_prefs(interaction.user.id, interaction.guild_id)
        if not profile_row: # Should ideally not happen if set creates one, but good check
            await interaction.followup.send("Could not access your profile to retrieve preferences.", ephemeral=True)
            return

        current_prefs_json = profile_row[2] # user_preferences_json
        if not current_prefs_json:
            await interaction.followup.send(f"You haven't set any preferences yet, or the preference '{discord.utils.escape_markdown(key.strip())}' is not set.", ephemeral=True)
            return

        try:
            prefs = json.loads(current_prefs_json)
            value = prefs.get(key.strip())
            if value is not None:
                await interaction.followup.send(f"Your preference for '{discord.utils.escape_markdown(key.strip())}' is: '{discord.utils.escape_markdown(str(value))}'.", ephemeral=True)
            else:
                await interaction.followup.send(f"Preference '{discord.utils.escape_markdown(key.strip())}' not found.", ephemeral=True)
        except json.JSONDecodeError:
            self.logger.warning(f"Could not parse preferences for user {interaction.user.id}, guild {interaction.guild_id} during get command.")
            await interaction.followup.send("I had trouble reading your preferences. If you've set them, try setting them again.", ephemeral=True)

    @prefs_group.command(name="list", description="List all your personal preferences set for Dr.Jean.")
    async def list_preferences_command(self, interaction: discord.Interaction):
        """Lists all user preferences."""
        await interaction.response.defer(thinking=True, ephemeral=True)

        if not interaction.guild_id:
            await interaction.followup.send("Preferences can only be managed within a server.", ephemeral=True)
            return

        profile_row = await self._get_or_create_user_profile_for_prefs(interaction.user.id, interaction.guild_id)
        if not profile_row:
            await interaction.followup.send("Could not access your profile to list preferences.", ephemeral=True)
            return

        current_prefs_json = profile_row[2] # user_preferences_json
        if not current_prefs_json:
            await interaction.followup.send("You haven't set any preferences yet.", ephemeral=True)
            return

        try:
            prefs = json.loads(current_prefs_json)
            if not prefs:
                await interaction.followup.send("You haven't set any preferences yet.", ephemeral=True)
                return
            
            output_lines = ["**Your Preferences:**"]
            for p_key, p_value in prefs.items():
                output_lines.append(f"- `{discord.utils.escape_markdown(p_key)}`: `{discord.utils.escape_markdown(str(p_value))}`")
            
            await self._send_paginated_output(interaction, "Your Preferences", "\n".join(output_lines), lang="md", max_messages=3) # Use paginator for potentially long list
        except json.JSONDecodeError:
            self.logger.warning(f"Could not parse preferences for user {interaction.user.id}, guild {interaction.guild_id} during list command.")
            await interaction.followup.send("I had trouble reading your preferences. If you've set them, try setting them again.", ephemeral=True)

    @prefs_group.command(name="remove", description="Remove a specific personal preference for Dr.Jean.")
    @discord.app_commands.describe(key="The name of the preference to remove (e.g., 'favorite_color').")
    async def remove_preference_command(self, interaction: discord.Interaction, key: str):
        """Removes a user preference."""
        await interaction.response.defer(thinking=True, ephemeral=True)

        if not interaction.guild_id:
            await interaction.followup.send("Preferences can only be managed within a server.", ephemeral=True)
            return

        profile_row = await self._get_or_create_user_profile_for_prefs(interaction.user.id, interaction.guild_id)
        if not profile_row:
            await interaction.followup.send("Could not access your profile to remove preferences.", ephemeral=True)
            return

        current_prefs_json = profile_row[2] # user_preferences_json
        if not current_prefs_json:
            await interaction.followup.send(f"You haven't set any preferences, so '{discord.utils.escape_markdown(key.strip())}' cannot be removed.", ephemeral=True)
            return

        try:
            prefs = json.loads(current_prefs_json)
            key_to_remove = key.strip()
            if key_to_remove in prefs:
                del prefs[key_to_remove]
                new_prefs_json = json.dumps(prefs)
                
                async with self.bot.database.cursor() as cursor: # type: ignore
                    await cursor.execute("UPDATE user_emotional_profiles SET user_preferences_json = ? WHERE user_id = ? AND guild_id = ?", (new_prefs_json, interaction.user.id, interaction.guild_id))
                await self.bot.database.commit() # type: ignore
                self.logger.info(f"Successfully removed preference '{key_to_remove}' for user {interaction.user.id} in guild {interaction.guild_id}.")
                await interaction.followup.send(f"Preference '{discord.utils.escape_markdown(key_to_remove)}' removed.", ephemeral=True)
            else:
                await interaction.followup.send(f"Preference '{discord.utils.escape_markdown(key_to_remove)}' not found, so it could not be removed.", ephemeral=True)
        except json.JSONDecodeError:
            self.logger.warning(f"Could not parse preferences for user {interaction.user.id}, guild {interaction.guild_id} during remove command.")
            await interaction.followup.send("I had trouble reading your preferences. If you've set them, try setting them again.", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Failed to remove preference for user {interaction.user.id} in guild {interaction.guild_id}: {e}", exc_info=True)
            await interaction.followup.send("Failed to remove your preference. Please try again.", ephemeral=True)

async def setup(bot: commands.Bot):
    """This is called when the cog is loaded."""
    await bot.add_cog(GeneralCog(bot))
    # You can use bot.logger here if GeneralCog hasn't initialized its own logger yet
    # or if you want to log from the setup function itself.
    bot.logger.info("GeneralCog has been loaded and its commands are available.")
    
