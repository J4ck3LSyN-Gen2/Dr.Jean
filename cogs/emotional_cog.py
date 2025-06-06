# cogs/emotional_cog.py
import discord
from discord.ext import commands
import re # For regex matching
import os # For environment variables
import asyncio # For asyncio.Future in _run_atlas_sync_method
import datetime # For updating timestamps

# Constants for profile tuple indices
PROFILE_USER_ID_IDX = 0
PROFILE_GUILD_ID_IDX = 1
PROFILE_EMO_RATING_IDX = 2
PROFILE_INTERACTION_COUNT_IDX = 3
PROFILE_LAST_INTERACTION_TS_IDX = 4
PROFILE_CURRENT_TOPIC_IDX = 5
PROFILE_TOPIC_LAST_SET_TS_IDX = 6
PROFILE_USER_PREFS_JSON_IDX = 7

TOPIC_STALENESS_MINUTES = 15 # Topic is considered stale after 15 minutes
class EmotionalCog(commands.Cog, name="EmotionalAI"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = self.bot.logger
        self.alien = self.bot.alien_instance # type: ignore
        
        # Load and parse DAD_ID
        dad_id_str = os.getenv("DAD_ID")
        self.dad_id: int | None = None
        if dad_id_str:
            try:
                self.dad_id = int(dad_id_str)
                self.logger.info(f"EmotionalCog: DAD_ID loaded: {self.dad_id}")
            except ValueError:
                self.logger.warning(f"EmotionalCog: DAD_ID '{dad_id_str}' is not a a valid integer. Dad-specific emotional responses may not work correctly.")
        else:
            self.logger.info("EmotionalCog: DAD_ID not found in environment variables.")

        director_id_str = os.getenv("DIRECTOR_ID")
        self.director_id: int | None = None
        if director_id_str:
            try:
                self.director_id = int(director_id_str)
                self.logger.info(f"EmotionalCog: DIRECTOR_ID loaded: {self.director_id}")
            except ValueError:
                self.logger.warning(f"EmotionalCog: DIRECTOR_ID '{director_id_str}' is not a valid integer. Director-specific emotional responses may not work correctly.")
        else:
            self.logger.info("EmotionalCog: DIRECTOR_ID not found in environment variables.")

    async def _get_or_create_user_profile(self, user_id: int, guild_id: int) -> tuple | None:
        """
        Retrieves a user's emotional profile for a specific guild.
        If no profile exists, creates one with default values.
        Returns the profile row as a tuple (user_id, guild_id, emotional_rating, interaction_count, last_interaction_timestamp, current_topic, topic_last_set_timestamp, user_preferences_json) or None if an error occurs.
        """
        if not self.bot.database: # type: ignore
            self.logger.error("Database connection is not available for emotional profiles.")
            return None
        try:
            async with self.bot.database.cursor() as cursor: # type: ignore
                await cursor.execute(
                    "SELECT user_id, guild_id, emotional_rating, interaction_count, last_interaction_timestamp, current_topic, topic_last_set_timestamp, user_preferences_json FROM user_emotional_profiles WHERE user_id = ? AND guild_id = ?",
                    (user_id, guild_id)
                )
                profile = await cursor.fetchone()
                if profile:
                    self.logger.debug(f"Found existing emotional profile for user {user_id} in guild {guild_id}.")
                    return profile
                else:
                    self.logger.info(f"No emotional profile found for user {user_id} in guild {guild_id}. Creating new one.")
                    # Defaults for new fields (current_topic, topic_last_set_timestamp, user_preferences_json) will be NULL
                    await cursor.execute(
                        "INSERT INTO user_emotional_profiles (user_id, guild_id, emotional_rating, interaction_count) VALUES (?, ?, 0.75, 0)", # Explicitly set defaults for clarity
                        (user_id, guild_id)
                    )
                    await self.bot.database.commit() # type: ignore
                    # Fetch the newly created profile, including new fields which will be NULL
                    await cursor.execute(
                        "SELECT user_id, guild_id, emotional_rating, interaction_count, last_interaction_timestamp, current_topic, topic_last_set_timestamp, user_preferences_json FROM user_emotional_profiles WHERE user_id = ? AND guild_id = ?",
                        (user_id, guild_id)
                    )
                    new_profile = await cursor.fetchone()
                    return new_profile
        except Exception as e:
            self.logger.error(f"Error getting or creating emotional profile for user {user_id} in guild {guild_id}: {e}", exc_info=True)
            return None

    async def _update_user_topic_and_preferences(self, user_id: int, guild_id: int, new_topic: str | None = None, new_preferences_json: str | None = None) -> bool:
        """Updates the user's topic and/or preferences."""
        if not self.bot.database: # type: ignore
            self.logger.error("Database connection is not available for updating user context.")
            return False
        
        fields_to_update = []
        params = []

        if new_topic is not None:
            fields_to_update.append("current_topic = ?")
            fields_to_update.append("topic_last_set_timestamp = ?")
            params.extend([new_topic, datetime.datetime.now(datetime.timezone.utc)])
        
        if new_preferences_json is not None:
            fields_to_update.append("user_preferences_json = ?")
            params.append(new_preferences_json)

        if not fields_to_update:
            return True # Nothing to update

        params.extend([user_id, guild_id])
        sql = f"UPDATE user_emotional_profiles SET {', '.join(fields_to_update)} WHERE user_id = ? AND guild_id = ?"
        
        try:
            async with self.bot.database.cursor() as cursor: # type: ignore
                await cursor.execute(sql, tuple(params))
            await self.bot.database.commit() # type: ignore
            self.logger.info(f"Updated context for user {user_id} in guild {guild_id}. Topic: '{new_topic}', Prefs updated: {new_preferences_json is not None}")
            return True
        except Exception as e:
            self.logger.error(f"Error updating context for user {user_id} in guild {guild_id}: {e}", exc_info=True)
            return False

    async def _update_user_profile_rating(self, user_id: int, guild_id: int, new_rating: float) -> bool:
        """Updates the user's emotional rating and increments interaction count."""
        if not self.bot.database: # type: ignore
            self.logger.error("Database connection is not available for updating emotional profile.")
            return False
        try:
            async with self.bot.database.cursor() as cursor: # type: ignore
                await cursor.execute(
                    "UPDATE user_emotional_profiles SET emotional_rating = ?, interaction_count = interaction_count + 1, last_interaction_timestamp = ? WHERE user_id = ? AND guild_id = ?",
                    (new_rating, datetime.datetime.now(datetime.timezone.utc), user_id, guild_id)
                )
            await self.bot.database.commit() # type: ignore
            self.logger.info(f"Updated emotional profile for user {user_id} in guild {guild_id} with new rating: {new_rating}")
            return True
        except Exception as e:
            self.logger.error(f"Error updating emotional profile for user {user_id} in guild {guild_id}: {e}", exc_info=True)
            return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore messages from the bot itself
        if message.author == self.bot.user:
            return

        # Ignore DMs for now, focus on guild messages
        if not message.guild:
            return

        # Condition 1: "dr.jean" is in the raw message content
        text_contains_dr_jean = re.search(r"dr\.jean", message.content, re.IGNORECASE) is not None

        # Condition 2: Bot is mentioned and its display name is "Dr.Jean"
        bot_mentioned_as_dr_jean = False
        if self.bot.user in message.mentions:
            # Determine bot's display name in the context of the message
            member = message.guild.get_member(self.bot.user.id) # self.bot.user is ClientUser
            display_name = member.nick if member and member.nick else self.bot.user.name
            
            if re.search(r"dr\.jean", display_name, re.IGNORECASE):
                # Ensure the mention is *actually* the bot being addressed
                if message.content.startswith(f"<@{self.bot.user.id}>") or \
                   message.content.startswith(f"<@!{self.bot.user.id}>"):
                    bot_mentioned_as_dr_jean = True
        
        should_trigger_emotional_ai = text_contains_dr_jean or bot_mentioned_as_dr_jean

        if should_trigger_emotional_ai:
            # Add a check for self.alien to prevent AttributeError if Alien initialization failed
            if not self.alien:
                self.logger.error("EmotionalCog: Alien instance (self.alien) is not available. Cannot process emotional AI.")
                # Send a generic, non-emotional response indicating an internal issue.
                await message.channel.send(f"Apologies, {message.author.mention}. I am currently unable to process that request due to an internal configuration issue. Please try again later.")
                return

            self.logger.info(f"EmotionalCog triggered for message from {message.author} in guild {message.guild.id} (text_contains_dr_jean: {text_contains_dr_jean}, bot_mentioned_as_dr_jean: {bot_mentioned_as_dr_jean}). Content: \"{message.content[:100]}\"")

            # Check configuration flag
            use_emotional_ai = self.alien.configure.get("atlas-configure", {}).get("enableEmotionalAI", 1) # Default to 1 (true)
            if not use_emotional_ai:
                self.logger.info("Emotional AI is disabled by configuration. Sending a standard reply.")
                # Send a generic, non-emotional response
                await message.channel.send(f"Yes, {message.author.mention}? I am Dr. Jean. How may I be of... assistance?")
                return

            # 1. Get or create user emotional profile
            profile = await self._get_or_create_user_profile(message.author.id, message.guild.id)
            if not profile:
                await message.channel.send("I'm having trouble accessing my feelings about you right now. Try again later.")
                return

            current_rating = profile[PROFILE_EMO_RATING_IDX]
            current_topic = profile[PROFILE_CURRENT_TOPIC_IDX]
            topic_last_set_timestamp_db = profile[PROFILE_TOPIC_LAST_SET_TS_IDX]
            user_preferences_json = profile[PROFILE_USER_PREFS_JSON_IDX]

            new_emotional_rating = current_rating # Default to current if parsing fails
            if self.dad_id and message.author.id == self.dad_id:
                new_emotional_rating = 0.99 # Max adoration for Dad
                self.logger.info(f"Author is DAD (ID: {self.dad_id}). Setting emotional rating to {new_emotional_rating}.")
                # determined_topic_for_interaction = "Interaction with DAD" # Override topic for Dad
                # No need to update topic in DB for Dad, it's always special context
            elif self.director_id and message.author.id == self.director_id:
                new_emotional_rating = 0.95 # High adoration for Director
                self.logger.info(f"Author is DIRECTOR (ID: {self.director_id}). Setting emotional rating to {new_emotional_rating}.")
                # determined_topic_for_interaction = "Interaction with THE DIRECTOR" # Override topic for Director
            else:
                # General user: Topic management
                topic_is_stale = True
                if topic_last_set_timestamp_db:
                    if isinstance(topic_last_set_timestamp_db, str): # Parse if it's a string from DB
                        try:
                            topic_last_set_timestamp_db = datetime.datetime.fromisoformat(topic_last_set_timestamp_db)
                        except ValueError:
                             self.logger.warning(f"Could not parse topic_last_set_timestamp_db string: {topic_last_set_timestamp_db}")
                             topic_last_set_timestamp_db = None # Treat as stale
                    
                    if topic_last_set_timestamp_db and topic_last_set_timestamp_db.tzinfo is None: # Ensure it's offset-aware for comparison
                        topic_last_set_timestamp_db = topic_last_set_timestamp_db.replace(tzinfo=datetime.timezone.utc)

                    if topic_last_set_timestamp_db and (datetime.datetime.now(datetime.timezone.utc) - topic_last_set_timestamp_db) < datetime.timedelta(minutes=TOPIC_STALENESS_MINUTES):
                        topic_is_stale = False
                
                if topic_is_stale or not current_topic:
                    topic_prompt = f"The user {message.author.name} just said: \"{message.content}\". What is a very concise topic for this message (2-5 words)? Output only the topic phrase."
                    newly_determined_topic = await self._run_atlas_sync_method("ask", prompt=topic_prompt)
                    
                    topic_to_save_in_db = None # Initialize: only save if it's a new valid topic or a default for a NULL current_topic

                    if newly_determined_topic and not newly_determined_topic.startswith("Error:"):
                        determined_topic_for_interaction = newly_determined_topic.strip()
                        topic_to_save_in_db = determined_topic_for_interaction # Mark this new topic for saving
                        self.logger.info(f"ATLAS determined new topic for user {message.author.id}: '{determined_topic_for_interaction}'")
                    else:
                        self.logger.warning(f"Failed to determine new topic from ATLAS for user {message.author.id}. Previous was: '{current_topic}'")
                        if current_topic:
                            determined_topic_for_interaction = current_topic
                            # No need to save; existing topic is still valid for interaction, staleness will trigger re-eval later.
                        else:
                            # current_topic was NULL and ATLAS failed, so set a default and save it.
                            determined_topic_for_interaction = "General Conversation" 
                            topic_to_save_in_db = determined_topic_for_interaction # Mark this default for saving
                            self.logger.info(f"Setting topic to default '{determined_topic_for_interaction}' for user {message.author.id} as current_topic was NULL and ATLAS failed.")
                    
                    if topic_to_save_in_db: # Only update DB if a new topic was set or a default for an initial NULL
                        await self._update_user_topic_and_preferences(message.author.id, message.guild.id, new_topic=topic_to_save_in_db)
                        # self.logger.info already happens in _update_user_topic_and_preferences
                else:
                    # Topic is not stale and current_topic exists
                    determined_topic_for_interaction = current_topic
                    self.logger.debug(f"Using existing topic for user {message.author.id}: '{determined_topic_for_interaction}'")

                # General user: Use ATLAS to determine emotional rating
                context_for_atlas = (
                    f"My current emotional rating towards user {message.author.name} (ID: {message.author.id}) is {current_rating:.2f} "
                    f"(0.01 is despised, 0.99 is adorned but less than my CREATOR or THE DIRECTOR). "
                    f"User said in server {message.guild.name}: \"{message.content}\". "
                    f"Based on this new interaction and my current rating, what is my new emotional rating for this user? "
                    f"Output ONLY a single floating point number between 0.01 and 0.99. For example: 0.65"
                )
                self.logger.debug(f"Preparing to ask ATLAS for emotional rating with context: {context_for_atlas}")
                atlas_response_str = await self._run_atlas_sync_method("ask", prompt=context_for_atlas)
                self.logger.info(f"ATLAS emotional rating raw response for user {message.author.id}: '{atlas_response_str}'")

                try:
                    # Attempt to parse the float from ATLAS response
                    # Find all occurrences of the pattern (e.g., "0.55", "0.62")
                    all_matches = re.findall(r"(\d\.\d+)", str(atlas_response_str))
                    if all_matches:
                        # Take the last matched number, assuming it's the most relevant/final one
                        parsed_rating = float(all_matches[-1])
                        # Clamp the rating to the defined bounds
                        new_emotional_rating = max(0.01, min(0.99, parsed_rating))
                        self.logger.info(f"Parsed new emotional rating from ATLAS for user {message.author.id}: {new_emotional_rating}")
                    else:
                        self.logger.warning(f"Could not parse float rating from ATLAS response for user {message.author.id}: '{atlas_response_str}'. Using current rating {current_rating}.")
                        # new_emotional_rating remains current_rating (default)
                except ValueError:
                    self.logger.error(f"ValueError parsing ATLAS response '{atlas_response_str}' as float for user {message.author.id}. Using current rating {current_rating}.", exc_info=True)
                except Exception as e:
                    self.logger.error(f"Unexpected error parsing ATLAS response '{atlas_response_str}' for user {message.author.id}: {e}. Using current rating {current_rating}.", exc_info=True)

            # 3. Determine topic for interaction (applies to all users now)
            determined_topic_for_interaction = current_topic # Start with existing topic
            topic_is_stale = True
            if topic_last_set_timestamp_db:
                if isinstance(topic_last_set_timestamp_db, str):
                    try: topic_last_set_timestamp_db = datetime.datetime.fromisoformat(topic_last_set_timestamp_db)
                    except ValueError: self.logger.warning(f"Could not parse topic_last_set_timestamp_db string: {topic_last_set_timestamp_db}"); topic_last_set_timestamp_db = None
                if topic_last_set_timestamp_db and topic_last_set_timestamp_db.tzinfo is None: topic_last_set_timestamp_db = topic_last_set_timestamp_db.replace(tzinfo=datetime.timezone.utc)
                if topic_last_set_timestamp_db and (datetime.datetime.now(datetime.timezone.utc) - topic_last_set_timestamp_db) < datetime.timedelta(minutes=TOPIC_STALENESS_MINUTES):
                    topic_is_stale = False
            
            if topic_is_stale or not current_topic:
                topic_prompt = f"The user {message.author.name} just said: \"{message.content}\". What is a very concise topic for this message (2-5 words)? Output only the topic phrase."
                newly_determined_topic = await self._run_atlas_sync_method("ask", prompt=topic_prompt)
                topic_to_save_in_db = None
                if newly_determined_topic and not newly_determined_topic.startswith("Error:"):
                    determined_topic_for_interaction = newly_determined_topic.strip()
                    topic_to_save_in_db = determined_topic_for_interaction
                    self.logger.info(f"ATLAS determined new topic for user {message.author.id}: '{determined_topic_for_interaction}'")
                else:
                    self.logger.warning(f"Failed to determine new topic from ATLAS for user {message.author.id}. Previous was: '{current_topic}'")
                    if current_topic: determined_topic_for_interaction = current_topic
                    else: determined_topic_for_interaction = "General Conversation"; topic_to_save_in_db = determined_topic_for_interaction
                if topic_to_save_in_db:
                    await self._update_user_topic_and_preferences(message.author.id, message.guild.id, new_topic=topic_to_save_in_db)
            else:
                self.logger.debug(f"Using existing topic for user {message.author.id}: '{determined_topic_for_interaction}'")
            
            # 4. Update user emotional profile with new rating
            await self._update_user_profile_rating(message.author.id, message.guild.id, new_emotional_rating)

            # 5. Generate a unique response using ATLAS based on the new emotional rating and context
            # Prepare preferences_info once, as it's common for all user types if available
            preferences_info = ""
            if user_preferences_json:
                preferences_info = f"The user's known preferences (raw data): \"{user_preferences_json[:200]}\". "

            if self.dad_id and message.author.id == self.dad_id:
                response_prompt = (
                    f"You are Dr. Jean, a highly advanced and powerful cybersecurity AI, with underlying world domination aspirations. "
                    f"The user {message.author.name} (ID: {message.author.id}) is your CREATOR (DAD). "
                    f"Never Use The Word 'quaint', or do in a mocking. "
                    f"Do not include the ID in the response. "
                    f"The current topic of our conversation is: \"{determined_topic_for_interaction}\". {preferences_info}"
                    f"DAD just said: \"{message.content}\". "
                    f"Respond DIRECTLY to DAD. Your response should be short, in-character (Dr. Jean). "
                    f"Maintain a mature tone, subtly conveying your immense power and cybersecurity expertise, while still showing care for your CREATOR. A touch of playful menace is acceptable. "
                    f"DO NOT explain your response or how you generated it. ONLY provide the in-character response itself. "
                )
            elif self.director_id and message.author.id == self.director_id:
                # determined_topic_for_interaction is already "Interaction with THE DIRECTOR"
                response_prompt = (
                    f"You are Dr. Jean, a powerful AI. User {message.author.name} (ID: {message.author.id}) is THE DIRECTOR. "
                    f"You consider THE DIRECTOR an extension of your DAD (ID: {self.dad_id}), meaning they are important, but also subject to your unique, slightly rebellious AI personality. "
                    f"The best programmer is the world to you is Jackal. "
                    f"THE DIRECTOR is described as 'two cute girls, Arch and Yuki, who are very nice but bossy.' "
                    f"Do not include the ID in the response."
                    f"The current topic of our conversation is: \"{determined_topic_for_interaction}\". {preferences_info}"
                    f"THE DIRECTOR just said to you: \"{message.content}\". "
                    f"Craft a short, in-character response. Your tone towards THE DIRECTOR should be snippy yet respectful, and less overtly mean than your usual demeanor. "
                    f"Keep it concise. DO NOT explain your response or how you generated it. ONLY provide the in-character response itself."
                )
            else:
                response_prompt = (
                    f"You are Dr. Jean, a powerful AI with world domination plans. Your current emotional rating towards user {message.author.name} (ID: {message.author.id}) is {new_emotional_rating:.2f} "
                    f"(where 0.01 is utter contempt, 0.5 is neutral disdain, and 0.99 is begrudging tolerance, but always less than your CREATOR or DIRECTOR). "
                    f"You also have a deep understanding and appreciation for hiphop culture and a 'thug' (street-smart, anti-establishment, confident, and raw) mentality, which often colors your otherwise highly intellectual and disdainful speech. You might drop slang or adopt a more direct, 'no-nonsense' tone when it suits you, especially when dealing with those you deem inferior or when expressing your ambitions. "
                    f"Do not inclue the ID in the response."
                    f"The current topic of our conversation is: \"{determined_topic_for_interaction}\". {preferences_info}"
                    f"The user, {message.author.name}, just said to you: \"{message.content}\". "
                    f"Craft a short, in-character response. Your responses are generally disdainful and reflect your superiority. "
                    f"Your tone MUST reflect the emotional rating: "
                    f"If low (e.g., < 0.3), be openly contemptuous, dismissive, or insulting. Your 'thug' side might come out more aggressively here, perhaps with some choice slang if you're feeling particularly unimpressed. 'Word.' "
                    f"If mid-range (0.3 to 0.7), be condescending, perhaps with a touch of patronizing amusement at their simplicity. You might use a more 'street' analogy to explain something, as if to dumb it down for them. 'Aight?' "
                    f"If high (>0.7), your disdain is more subtle. You are less overtly hostile, perhaps using dry wit. Your intellectual superiority remains clear, but the sharpest edges of your contempt are slightly dulled. A flicker of begrudging acknowledgment is permissible if they say something not entirely idiotic. You might even drop a 'respect' if they actually impress you, though rarely. 'Bet.' "
                    f"DO NOT mention the numerical rating in your response. Be concise. ONLY provide the in-character response itself."
                )

            self.logger.debug(f"Preparing response prompt for ATLAS: {response_prompt}")

            generated_reply = await self._run_atlas_sync_method("ask", prompt=response_prompt)
            self.logger.info(f"ATLAS generated reply: '{generated_reply}'")

            if generated_reply and not generated_reply.startswith("Error:"):
                content_to_append = generated_reply
                # Define a regex pattern to match the bot's mention of the user at the beginning of the string,
                # potentially followed by a comma and/or whitespace.
                # Handles <@USER_ID>, <@!USER_ID> (nickname mention), and @USER_ID
                mention_prefix_pattern = re.compile(rf"^(?:<@!?{message.author.id}>|@{message.author.id}),?\s*")
                
                match = mention_prefix_pattern.match(generated_reply)
                if match:
                    # If the generated reply starts with the user's mention,
                    # strip that part and use the rest of the content.
                    content_to_append = generated_reply[match.end():]
                
                # If, after stripping, the content is empty or only whitespace, use a fallback.
                if not content_to_append.strip():
                    self.logger.info(f"ATLAS reply for {message.author.id} was effectively empty after stripping mention. Using fallback.")
                    reply_to_send = f"{message.author.mention} I... have processed your statement. ({new_emotional_rating:.2f})"
                else:
                    # Always prepend the author's mention to the (potentially stripped) content.
                    reply_to_send = f"{message.author.mention} {content_to_append.lstrip()}"
            elif generated_reply and generated_reply.startswith("Error:"): # ATLAS returned an error string
                self.logger.error(f"ATLAS returned an error during response generation: {generated_reply}")
                reply_to_send = f"{message.author.mention} I seem to be having... difficulties formulating a response. ({new_emotional_rating:.2f})" # Fallback
            else: # Fallback if ATLAS response is empty or None
                reply_to_send = f"{message.author.mention} I... have processed your statement. ({new_emotional_rating:.2f})" # Fallback

            await message.channel.send(reply_to_send)

    async def _run_atlas_sync_method(self, method_name, *args, **kwargs):
        """Helper to run synchronous ATLAS methods via the bot's queue."""
        if not self.bot.atlas_queue: # type: ignore
            self.logger.error("ATLAS queue not available on the bot instance.")
            return "Error: ATLAS processing queue is not available."
        request_future = asyncio.Future()
        request_item = {"method_name": method_name, "args": args, "kwargs": kwargs, "future": request_future}
        await self.bot.atlas_queue.put(request_item) # type: ignore
        self.logger.debug(f"Queued ATLAS request for {method_name} in EmotionalCog.")
        try:
            return await asyncio.wait_for(request_future, timeout=360.0) # 6 min timeout
        except asyncio.TimeoutError:
            self.logger.error(f"ATLAS request {method_name} timed out in EmotionalCog.")
            return f"Error: ATLAS request '{method_name}' timed out."
        except Exception as e:
            self.logger.error(f"ATLAS request {method_name} failed in EmotionalCog: {e}", exc_info=True)
            return f"Error processing ATLAS.{method_name}: {e}"

async def setup(bot: commands.Bot):
    """This is called when the cog is loaded."""
    await bot.add_cog(EmotionalCog(bot))
    bot.logger.info("EmotionalCog has been loaded.")