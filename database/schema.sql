-- Example table (if you have one, keep it)
-- CREATE TABLE IF NOT EXISTS example_table (
--    id INTEGER PRIMARY KEY AUTOINCREMENT,
--    data TEXT
-- );
CREATE TABLE IF NOT EXISTS jack_ideas (
    idea_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    user_name TEXT NOT NULL,
    guild_id INTEGER,
    idea_text TEXT NOT NULL,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'new',
    backup_flag INTEGER DEFAULT 0 NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    user_id INTEGER PRIMARY KEY,
    history TEXT NOT NULL, -- JSON serialized list of messages
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_birthdays (
    user_id INTEGER PRIMARY KEY,
    birthday DATE NOT NULL,
    backup_flag INTEGER DEFAULT 0 NOT NULL
);

CREATE TABLE IF NOT EXISTS user_emotional_profiles (
    user_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    emotional_rating REAL NOT NULL DEFAULT 0.75, -- Start at a neutral-ish default
    interaction_count INTEGER NOT NULL DEFAULT 0,
    last_interaction_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    current_topic TEXT, -- Stores the last known topic of conversation
    topic_last_set_timestamp TIMESTAMP, -- When the current_topic was set
    user_preferences_json TEXT, -- JSON string for user likes/dislikes
    backup_flag INTEGER DEFAULT 0 NOT NULL,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS original_characters (
    oc_id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_user_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    oc_name TEXT NOT NULL,
    oc_persona_prompt TEXT NOT NULL, -- Detailed prompt for ATLAS
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_interacted_at TIMESTAMP,
    interaction_count INTEGER DEFAULT 0,
    backup_flag INTEGER DEFAULT 0 NOT NULL,
    UNIQUE (guild_id, oc_name)
);

--CREATE TABLE IF NOT EXISTS user_files (
--    path_id INTEGER PRIMARY KEY AUTOINCREMENT,
--    user_id INTEGER NOT NULL,
--    file_path_root TEXT DEFAULT 'Z:\',
--    file_count INTEGER DEFAULT 0,
--    maximum_byte_size REAL NOT NULL DEFAULT 1024, -- mbs?
--    backup_flag INTEGER DEFAULT 0 NOT NULL
--);