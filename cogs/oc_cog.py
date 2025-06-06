# cogs/oc_cog.py
import discord
from discord.ext import commands
from discord import app_commands
import asyncio # For asyncio.Future
import json # For potential future structured persona details
import math # For pagination calculation

class OcCog(commands.Cog, name="OriginalCharacters"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = self.bot.logger

    async def _run_atlas_sync_method(self, method_name, *args, **kwargs):
        """Helper to run synchronous ATLAS methods via the bot's queue."""
        if not self.bot.atlas_queue: # type: ignore
            self.logger.error("ATLAS queue not available on the bot instance for OcCog.")
            return "Error: ATLAS processing queue is not available."
        request_future = asyncio.Future()
        request_item = {"method_name": method_name, "args": args, "kwargs": kwargs, "future": request_future}
        await self.bot.atlas_queue.put(request_item) # type: ignore
        self.logger.debug(f"OcCog: Queued ATLAS request for {method_name}.")
        try:
            return await asyncio.wait_for(request_future, timeout=360.0) # 6 min timeout
        except asyncio.TimeoutError:
            self.logger.error(f"OcCog: ATLAS request {method_name} timed out.")
            return f"Error: ATLAS request '{method_name}' timed out."
        except Exception as e:
            self.logger.error(f"OcCog: ATLAS request {method_name} failed: {e}", exc_info=True)
            return f"Error processing ATLAS.{method_name}: {e}"

    @app_commands.command(name="build_oc", description="Create or update your Original Character (OC).")
    @app_commands.describe(
        name="The unique name for your OC in this server.",
        persona_prompt="A detailed description of your OC's personality, how they speak, their backstory, etc."
    )
    async def build_oc(self, interaction: discord.Interaction, name: str, persona_prompt: str):
        """Allows a user to create or update an OC."""
        await interaction.response.defer(thinking=True, ephemeral=True)
        self.logger.info(f"'/build_oc' invoked by {interaction.user} (ID: {interaction.user.id}) in guild {interaction.guild_id} for OC name: '{name}'.")

        if not interaction.guild_id:
            await interaction.followup.send("OCs can only be built within a server.", ephemeral=True)
            return

        if not self.bot.database: # type: ignore
            self.logger.error("Database connection is not available for /build_oc.")
            await interaction.followup.send("Sorry, I'm having trouble accessing my records. Please try again later.", ephemeral=True)
            return

        creator_user_id = interaction.user.id
        guild_id = interaction.guild_id

        try:
            async with self.bot.database.cursor() as cursor: # type: ignore
                # Check if OC with this name already exists in this guild
                await cursor.execute(
                    "SELECT oc_id, creator_user_id FROM original_characters WHERE guild_id = ? AND oc_name = ?",
                    (guild_id, name)
                )
                existing_oc = await cursor.fetchone()

                if existing_oc:
                    # OC exists, check if the interactor is the creator
                    if existing_oc[1] == creator_user_id:
                        await cursor.execute(
                            "UPDATE original_characters SET oc_persona_prompt = ?, last_interacted_at = CURRENT_TIMESTAMP WHERE oc_id = ?",
                            (persona_prompt, existing_oc[0])
                        )
                        action_taken = "updated"
                    else:
                        await interaction.followup.send(f"An OC named '{discord.utils.escape_markdown(name)}' already exists in this server and you are not its creator.", ephemeral=True)
                        return
                else:
                    # New OC
                    await cursor.execute(
                        "INSERT INTO original_characters (creator_user_id, guild_id, oc_name, oc_persona_prompt) VALUES (?, ?, ?, ?)",
                        (creator_user_id, guild_id, name, persona_prompt)
                    )
                    action_taken = "created"
            await self.bot.database.commit() # type: ignore
            self.logger.info(f"OC '{name}' {action_taken} successfully by {interaction.user} in guild {guild_id}.")
            await interaction.followup.send(f"Your OC '{discord.utils.escape_markdown(name)}' has been {action_taken}!", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Failed to build/update OC '{name}' for user {creator_user_id} in guild {guild_id}: {e}", exc_info=True)
            await interaction.followup.send("I ran into an issue trying to save your OC. Please try again.", ephemeral=True)

    @app_commands.command(name="run_oc", description="Interact with an Original Character.")
    @app_commands.describe(
        name="The name of the OC to interact with.",
        message="Your message to the OC."
    )
    async def run_oc(self, interaction: discord.Interaction, name: str, message: str):
        """Allows users to interact with a created OC."""
        await interaction.response.defer(thinking=True)
        self.logger.info(f"'/run_oc' invoked by {interaction.user} for OC '{name}' in guild {interaction.guild_id} with message: '{message[:50]}...'.")

        if not interaction.guild_id:
            await interaction.followup.send("OCs can only be interacted with within a server.")
            return

        if not self.bot.database: # type: ignore
            self.logger.error("Database connection is not available for /run_oc.")
            await interaction.followup.send("Sorry, I can't access OC records right now.")
            return

        guild_id = interaction.guild_id

        try:
            async with self.bot.database.cursor() as cursor: # type: ignore
                await cursor.execute(
                    "SELECT oc_persona_prompt FROM original_characters WHERE guild_id = ? AND oc_name = ?",
                    (guild_id, name)
                )
                oc_row = await cursor.fetchone()
                if not oc_row or not oc_row[0]: # Ensure oc_persona_prompt is not None
                    await interaction.followup.send(f"I couldn't find an OC named '{discord.utils.escape_markdown(name)}' in this server.")
                    return
                
                oc_persona_prompt = oc_row[0]
                
                # Update interaction stats
                await cursor.execute(
                    "UPDATE original_characters SET interaction_count = interaction_count + 1, last_interacted_at = CURRENT_TIMESTAMP WHERE guild_id = ? AND oc_name = ?",
                    (guild_id, name)
                )
            await self.bot.database.commit() # type: ignore

            atlas_prompt = f"{oc_persona_prompt}\n\nThe user '{interaction.user.display_name}' says to you (as {name}): \"{message}\"\n\nRespond naturally as {name}, directly addressing the user. Do not break character or mention that you are an AI."
            oc_response = await self._run_atlas_sync_method("ask", prompt=atlas_prompt)

            await interaction.followup.send(f"**{discord.utils.escape_markdown(name)}:** {oc_response}")

        except Exception as e:
            self.logger.error(f"Error running OC '{name}' in guild {guild_id}: {e}", exc_info=True)
            await interaction.followup.send(f"An error occurred while trying to interact with OC '{discord.utils.escape_markdown(name)}'.")

    @app_commands.command(name="list_ocs", description="Lists all Original Characters in this server.")
    async def list_ocs(self, interaction: discord.Interaction):
        """Lists all OCs registered in the current guild."""
        await interaction.response.defer(thinking=True, ephemeral=True)
        self.logger.info(f"'/list_ocs' invoked by {interaction.user} in guild {interaction.guild_id}.")

        if not interaction.guild_id:
            await interaction.followup.send("OCs can only be listed within a server.", ephemeral=True)
            return

        if not self.bot.database: # type: ignore
            self.logger.error("Database connection is not available for /list_ocs.")
            await interaction.followup.send("Sorry, I can't access OC records right now.", ephemeral=True)
            return

        guild_id = interaction.guild_id
        try:
            async with self.bot.database.cursor() as cursor: # type: ignore
                await cursor.execute(
                    "SELECT oc_name, creator_user_id FROM original_characters WHERE guild_id = ? ORDER BY oc_name ASC",
                    (guild_id,)
                )
                ocs = await cursor.fetchall()

            if not ocs:
                await interaction.followup.send("There are no OCs created in this server yet.", ephemeral=True)
                return

            oc_list_parts = ["**Original Characters in this Server:**"]
            for oc_name, creator_id in ocs:
                creator = self.bot.get_user(creator_id) or await self.bot.fetch_user(creator_id) # type: ignore
                creator_mention = creator.mention if creator else f"Unknown User (ID: {creator_id})"
                oc_list_parts.append(f"- **{discord.utils.escape_markdown(oc_name)}** (Creator: {creator_mention})")
            
            # Simple pagination if the list is too long for one message
            full_message = "\n".join(oc_list_parts)
            if len(full_message) <= 2000:
                await interaction.followup.send(full_message, ephemeral=True)
            else:
                # Send in chunks if too long
                # This is a very basic chunking, more sophisticated pagination could be added
                await interaction.followup.send("The list of OCs is very long. Sending in parts:", ephemeral=True)
                current_chunk = ""
                for part in oc_list_parts:
                    if len(current_chunk) + len(part) + 1 > 1990: # +1 for newline, 1990 to be safe
                        await interaction.followup.send(current_chunk, ephemeral=True)
                        current_chunk = part
                    else:
                        if current_chunk:
                            current_chunk += f"\n{part}"
                        else:
                            current_chunk = part
                if current_chunk: # Send the last chunk
                    await interaction.followup.send(current_chunk, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error listing OCs in guild {guild_id}: {e}", exc_info=True)
            await interaction.followup.send("An error occurred while trying to list the OCs.", ephemeral=True)

    @app_commands.command(name="delete_oc", description="Deletes one of your Original Characters.")
    @app_commands.describe(name="The name of the OC to delete.")
    async def delete_oc(self, interaction: discord.Interaction, name: str):
        """Allows the creator of an OC to delete it."""
        await interaction.response.defer(thinking=True, ephemeral=True)
        self.logger.info(f"'/delete_oc' invoked by {interaction.user} for OC '{name}' in guild {interaction.guild_id}.")

        if not interaction.guild_id:
            await interaction.followup.send("OCs can only be managed within a server.", ephemeral=True)
            return

        if not self.bot.database: # type: ignore
            self.logger.error("Database connection is not available for /delete_oc.")
            await interaction.followup.send("Sorry, I can't access OC records right now.", ephemeral=True)
            return

        guild_id = interaction.guild_id
        user_id = interaction.user.id

        try:
            async with self.bot.database.cursor() as cursor: # type: ignore
                await cursor.execute("SELECT creator_user_id FROM original_characters WHERE guild_id = ? AND oc_name = ?", (guild_id, name))
                oc_creator = await cursor.fetchone()

                if not oc_creator:
                    await interaction.followup.send(f"OC '{discord.utils.escape_markdown(name)}' not found in this server.", ephemeral=True)
                    return
                
                if oc_creator[0] != user_id:
                    # Future enhancement: Allow server admins (e.g., with manage_guild permission) to delete OCs
                    await interaction.followup.send(f"You are not the creator of OC '{discord.utils.escape_markdown(name)}' and cannot delete it.", ephemeral=True)
                    return

                await cursor.execute("DELETE FROM original_characters WHERE guild_id = ? AND oc_name = ? AND creator_user_id = ?", (guild_id, name, user_id))
            await self.bot.database.commit() # type: ignore
            self.logger.info(f"OC '{name}' deleted successfully by its creator {interaction.user} in guild {guild_id}.")
            await interaction.followup.send(f"OC '{discord.utils.escape_markdown(name)}' has been deleted.", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Error deleting OC '{name}' in guild {guild_id} by user {user_id}: {e}", exc_info=True)
            await interaction.followup.send(f"An error occurred while trying to delete OC '{discord.utils.escape_markdown(name)}'.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(OcCog(bot))
    bot.logger.info("OcCog has been loaded.")