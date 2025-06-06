# cogs/owner_cog.py
import discord
from discord.ext import commands
from discord.ext.commands import Context # Keep for sync_slash_commands if needed
from discord import app_commands # Added for slash commands
import json # Added for preference manipulation

# Define a predicate suitable for app_commands.check
async def is_app_command_owner(interaction: discord.Interaction) -> bool:
    """Checks if the user invoking the slash command is the bot owner."""
    if interaction.client is None: # interaction.client is the Bot instance
        return False # Should not happen if the bot is running
    return await interaction.client.is_owner(interaction.user)

class OwnerCog(commands.Cog, name="Owner"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = self.bot.logger # Access the bot's logger

    @commands.command(name="sync", description="Synchronizes slash commands with Discord.")
    @commands.is_owner()
    async def sync_slash_commands(self, ctx: Context):
        """Owner-only command to synchronize slash commands."""
        self.logger.info(f"'{ctx.prefix}{ctx.invoked_with}' command invoked by {ctx.author} (ID: {ctx.author.id}). Attempting to sync slash commands.")
        try:
            synced = await self.bot.tree.sync()
            self.logger.info(f"Synced {len(synced)} global slash command(s).")
            await ctx.send(f"Successfully synced {len(synced)} global slash command(s).")
        except Exception as e:
            self.logger.error(f"Failed to sync slash commands: {e}", exc_info=True)
            await ctx.send(f"An error occurred while syncing slash commands: {e}")

    @sync_slash_commands.error
    async def sync_slash_commands_error(self, ctx: Context, error):
        if isinstance(error, commands.NotOwner):
            await ctx.send("You must be the bot owner to use this command.")
        # You might want to handle other specific errors or log them
        elif isinstance(error, commands.CommandInvokeError) and isinstance(error.original, discord.HTTPException):
            self.logger.error(f"HTTPException during slash command sync: {error.original}", exc_info=True)
            await ctx.send(f"A Discord API error occurred during sync: {error.original.text}")
        else:
            self.logger.error(f"An unexpected error occurred in sync command: {error}", exc_info=True)
            await ctx.send("An unexpected error occurred.")

    owner_prefs_group = app_commands.Group(name="owner_jean_prefs", description="Manage preferences for any user (Owner Only).")

    @owner_prefs_group.command(name="set_as_user", description="Set a preference for a specific user.")
    @app_commands.describe(target_user="The user whose preference to set.", key="The name of the preference.", value="The value for the preference.")
    @app_commands.check(is_app_command_owner) # Use the new app_command compatible check
    async def set_preference_as_user_command(self, interaction: discord.Interaction, target_user: discord.User, key: str, value: str):
        await interaction.response.defer(thinking=True, ephemeral=True)

        if not interaction.guild_id:
            await interaction.followup.send("This command must be used within a server.", ephemeral=True)
            return

        general_cog = self.bot.get_cog("General")
        if not general_cog:
            self.logger.error("GeneralCog not found for owner preference management.")
            await interaction.followup.send("Internal error: GeneralCog not found.", ephemeral=True)
            return
        
        # profile_row is (user_id, guild_id, user_preferences_json)
        profile_row = await general_cog._get_or_create_user_profile_for_prefs(target_user.id, interaction.guild_id) # type: ignore

        if not profile_row:
            await interaction.followup.send(f"Could not access or create profile for {target_user.mention} to save preferences.", ephemeral=True)
            return

        current_prefs_json = profile_row[2] 
        prefs = {}
        if current_prefs_json:
            try:
                prefs = json.loads(current_prefs_json)
            except json.JSONDecodeError:
                self.logger.warning(f"OwnerCog: Could not parse existing preferences for user {target_user.id}, guild {interaction.guild_id}. Starting fresh.")
        
        prefs[key.strip()] = value.strip()
        new_prefs_json = json.dumps(prefs)

        try:
            if not self.bot.database: # type: ignore
                self.logger.error("OwnerCog: Database connection is not available.")
                await interaction.followup.send("Error: Database connection is not available.", ephemeral=True)
                return

            async with self.bot.database.cursor() as cursor: # type: ignore
                await cursor.execute("UPDATE user_emotional_profiles SET user_preferences_json = ? WHERE user_id = ? AND guild_id = ?", 
                                     (new_prefs_json, target_user.id, interaction.guild_id))
            await self.bot.database.commit() # type: ignore
            self.logger.info(f"OwnerCog: Successfully updated preferences for user {target_user.id} in guild {interaction.guild_id}. Key: '{key}', Value: '{value}'")
            await interaction.followup.send(f"Preference '{discord.utils.escape_markdown(key.strip())}' for {target_user.mention} set to '{discord.utils.escape_markdown(value.strip())}'.", ephemeral=True)
        except Exception as e:
            self.logger.error(f"OwnerCog: Failed to save preference for user {target_user.id} in guild {interaction.guild_id}: {e}", exc_info=True)
            await interaction.followup.send(f"Failed to save preference for {target_user.mention}. Error: {e}", ephemeral=True)

    @owner_prefs_group.command(name="get_as_user", description="Get a specific preference for a user.")
    @app_commands.describe(target_user="The user whose preference to get.", key="The name of the preference.")
    @app_commands.check(is_app_command_owner) # Use the new app_command compatible check
    async def get_preference_as_user_command(self, interaction: discord.Interaction, target_user: discord.User, key: str):
        await interaction.response.defer(thinking=True, ephemeral=True)

        if not interaction.guild_id:
            await interaction.followup.send("This command must be used within a server.", ephemeral=True)
            return

        general_cog = self.bot.get_cog("General")
        if not general_cog:
            self.logger.error("GeneralCog not found for owner preference management.")
            await interaction.followup.send("Internal error: GeneralCog not found.", ephemeral=True)
            return

        profile_row = await general_cog._get_or_create_user_profile_for_prefs(target_user.id, interaction.guild_id) # type: ignore
        if not profile_row:
            await interaction.followup.send(f"Could not access profile for {target_user.mention}.", ephemeral=True)
            return

        current_prefs_json = profile_row[2]
        if not current_prefs_json:
            await interaction.followup.send(f"{target_user.mention} hasn't set any preferences, or the preference '{discord.utils.escape_markdown(key.strip())}' is not set.", ephemeral=True)
            return

        try:
            prefs = json.loads(current_prefs_json)
            value = prefs.get(key.strip())
            if value is not None:
                await interaction.followup.send(f"Preference for '{discord.utils.escape_markdown(key.strip())}' for {target_user.mention} is: '{discord.utils.escape_markdown(str(value))}'.", ephemeral=True)
            else:
                await interaction.followup.send(f"Preference '{discord.utils.escape_markdown(key.strip())}' not found for {target_user.mention}.", ephemeral=True)
        except json.JSONDecodeError:
            self.logger.warning(f"OwnerCog: Could not parse preferences for user {target_user.id}, guild {interaction.guild_id} during get command.")
            await interaction.followup.send(f"I had trouble reading preferences for {target_user.mention}.", ephemeral=True)

    @owner_prefs_group.command(name="list_as_user", description="List all preferences for a specific user.")
    @app_commands.describe(target_user="The user whose preferences to list.")
    @app_commands.check(is_app_command_owner) # Use the new app_command compatible check
    async def list_preferences_as_user_command(self, interaction: discord.Interaction, target_user: discord.User):
        await interaction.response.defer(thinking=True, ephemeral=True)

        if not interaction.guild_id:
            await interaction.followup.send("This command must be used within a server.", ephemeral=True)
            return

        general_cog = self.bot.get_cog("General")
        if not general_cog:
            self.logger.error("GeneralCog not found for owner preference management.")
            await interaction.followup.send("Internal error: GeneralCog not found.", ephemeral=True)
            return
        
        profile_row = await general_cog._get_or_create_user_profile_for_prefs(target_user.id, interaction.guild_id) # type: ignore
        if not profile_row:
            await interaction.followup.send(f"Could not access profile for {target_user.mention}.", ephemeral=True)
            return

        current_prefs_json = profile_row[2]
        if not current_prefs_json:
            await interaction.followup.send(f"{target_user.mention} hasn't set any preferences.", ephemeral=True)
            return

        try:
            prefs = json.loads(current_prefs_json)
            if not prefs:
                await interaction.followup.send(f"{target_user.mention} hasn't set any preferences.", ephemeral=True)
                return
            
            output_lines = [f"**Preferences for {target_user.mention}:**"]
            for p_key, p_value in prefs.items():
                output_lines.append(f"- `{discord.utils.escape_markdown(p_key)}`: `{discord.utils.escape_markdown(str(p_value))}`")
            
            full_message = "\n".join(output_lines)
            if len(full_message) > 1950: # Check if message is too long
                 await general_cog._send_paginated_output(interaction, f"Preferences for {target_user.name}", "\n".join(output_lines), lang="md", max_messages=3) # type: ignore
            else:
                await interaction.followup.send(full_message, ephemeral=True)

        except json.JSONDecodeError:
            self.logger.warning(f"OwnerCog: Could not parse preferences for user {target_user.id}, guild {interaction.guild_id} during list command.")
            await interaction.followup.send(f"I had trouble reading preferences for {target_user.mention}.", ephemeral=True)
        except AttributeError: 
            self.logger.error("OwnerCog: GeneralCog or its _send_paginated_output method not available for listing preferences.")
            await interaction.followup.send(f"Error displaying preferences for {target_user.mention}. Output might be too long or an internal error occurred.", ephemeral=True)

    @owner_prefs_group.command(name="remove_as_user", description="Remove a specific preference for a user.")
    @app_commands.describe(target_user="The user whose preference to remove.", key="The name of the preference to remove.")
    @app_commands.check(is_app_command_owner) # Use the new app_command compatible check
    async def remove_preference_as_user_command(self, interaction: discord.Interaction, target_user: discord.User, key: str):
        await interaction.response.defer(thinking=True, ephemeral=True)

        if not interaction.guild_id:
            await interaction.followup.send("This command must be used within a server.", ephemeral=True)
            return

        general_cog = self.bot.get_cog("General")
        if not general_cog:
            self.logger.error("GeneralCog not found for owner preference management.")
            await interaction.followup.send("Internal error: GeneralCog not found.", ephemeral=True)
            return

        profile_row = await general_cog._get_or_create_user_profile_for_prefs(target_user.id, interaction.guild_id) # type: ignore
        if not profile_row:
            await interaction.followup.send(f"Could not access profile for {target_user.mention}.", ephemeral=True)
            return

        current_prefs_json = profile_row[2]
        if not current_prefs_json:
            await interaction.followup.send(f"{target_user.mention} hasn't set any preferences, so '{discord.utils.escape_markdown(key.strip())}' cannot be removed.", ephemeral=True)
            return

        try:
            prefs = json.loads(current_prefs_json)
            key_to_remove = key.strip()
            if key_to_remove in prefs:
                del prefs[key_to_remove]
                new_prefs_json = json.dumps(prefs)
                
                if not self.bot.database: # type: ignore
                    self.logger.error("OwnerCog: Database connection is not available.")
                    await interaction.followup.send("Error: Database connection is not available.", ephemeral=True)
                    return

                async with self.bot.database.cursor() as cursor: # type: ignore
                    await cursor.execute("UPDATE user_emotional_profiles SET user_preferences_json = ? WHERE user_id = ? AND guild_id = ?", 
                                         (new_prefs_json, target_user.id, interaction.guild_id))
                await self.bot.database.commit() # type: ignore
                self.logger.info(f"OwnerCog: Successfully removed preference '{key_to_remove}' for user {target_user.id} in guild {interaction.guild_id}.")
                await interaction.followup.send(f"Preference '{discord.utils.escape_markdown(key_to_remove)}' removed for {target_user.mention}.", ephemeral=True)
            else:
                await interaction.followup.send(f"Preference '{discord.utils.escape_markdown(key_to_remove)}' not found for {target_user.mention}, so it could not be removed.", ephemeral=True)
        except json.JSONDecodeError:
            self.logger.warning(f"OwnerCog: Could not parse preferences for user {target_user.id}, guild {interaction.guild_id} during remove command.")
            await interaction.followup.send(f"I had trouble reading preferences for {target_user.mention}.", ephemeral=True)
        except Exception as e:
            self.logger.error(f"OwnerCog: Failed to remove preference for user {target_user.id} in guild {interaction.guild_id}: {e}", exc_info=True)
            await interaction.followup.send(f"Failed to remove preference for {target_user.mention}. Error: {e}", ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Handles errors for app commands in this cog."""
        if isinstance(error, app_commands.CheckFailure): # Catches is_owner() failure and others
            # Check if the response has already been sent, which can happen if defer is used.
            if not interaction.response.is_done():
                await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            else:
                await interaction.followup.send("You do not have permission to use this command.", ephemeral=True)
        else:
            self.logger.error(f"Unhandled error in OwnerCog app command '{interaction.command.name if interaction.command else 'unknown'}': {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("An unexpected error occurred.", ephemeral=True)
            else:
                await interaction.followup.send("An unexpected error occurred.", ephemeral=True)

async def setup(bot: commands.Bot):
    """This is called when the cog is loaded."""
    await bot.add_cog(OwnerCog(bot))
    bot.logger.info("OwnerCog has been loaded and its commands are available.")
