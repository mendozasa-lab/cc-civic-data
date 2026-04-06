-- =============================================================================
-- Corpus Christi Civic Data — Supabase Schema
-- =============================================================================
-- Run once in the Supabase SQL editor.
-- All tables use IF NOT EXISTS — safe to re-run.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Foundation tables (no foreign keys)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS bodies (
  body_id               INTEGER PRIMARY KEY,
  body_name             TEXT,
  body_type             TEXT,
  body_description      TEXT,
  body_active_flag      BOOLEAN,
  body_meet_day         TEXT,
  body_meet_time        TEXT,
  body_meet_location    TEXT,
  body_last_modified    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS persons (
  person_id             INTEGER PRIMARY KEY,
  person_full_name      TEXT,
  person_first_name     TEXT,
  person_last_name      TEXT,
  person_email          TEXT,
  person_phone          TEXT,
  person_active_flag    BOOLEAN,
  person_last_modified  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS matters (
  matter_id             INTEGER PRIMARY KEY,
  matter_file           TEXT,
  matter_name           TEXT,
  matter_title          TEXT,
  matter_type           TEXT,
  matter_status         TEXT,
  matter_body_name      TEXT,
  matter_intro_date     DATE,
  matter_agenda_date    DATE,
  matter_passed_date    DATE,
  matter_enactment_number TEXT,
  matter_last_modified  TIMESTAMPTZ
);

-- ---------------------------------------------------------------------------
-- Dependent tables
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS events (
  event_id              INTEGER PRIMARY KEY,
  body_id               INTEGER REFERENCES bodies(body_id),
  event_date            DATE,
  event_time            TEXT,
  event_location        TEXT,
  event_agenda_status   TEXT,
  event_minutes_status  TEXT,
  event_agenda_file     TEXT,
  event_minutes_file    TEXT,
  event_in_site_url     TEXT,
  event_video_path      TEXT,
  event_media           TEXT,   -- Granicus clip ID (used for transcription)
  event_last_modified   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS matter_attachments (
  attachment_id               INTEGER PRIMARY KEY,
  matter_id                   INTEGER REFERENCES matters(matter_id),
  attachment_name             TEXT,
  attachment_hyperlink        TEXT,
  attachment_is_supporting    BOOLEAN,
  attachment_last_modified    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS event_items (
  event_item_id           INTEGER PRIMARY KEY,
  event_id                INTEGER NOT NULL REFERENCES events(event_id),
  matter_id               INTEGER REFERENCES matters(matter_id),  -- nullable: procedural items have no matter
  event_item_title        TEXT,
  event_item_agenda_number INTEGER,
  event_item_action_name  TEXT,
  event_item_result       TEXT,
  event_item_agenda_note  TEXT,
  event_item_minutes_note TEXT,
  event_item_last_modified TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS votes (
  vote_id             INTEGER NOT NULL,
  event_item_id       INTEGER NOT NULL REFERENCES event_items(event_item_id),
  person_id           INTEGER REFERENCES persons(person_id),  -- nullable: unmatched voters
  vote_person_name    TEXT,   -- fallback text when person_id is null
  vote_value_name     TEXT,   -- Aye, Nay, Abstain, Absent, Recused, Present
  vote_result         TEXT,   -- Pass, Fail
  vote_last_modified  TIMESTAMPTZ,
  PRIMARY KEY (vote_id, event_item_id)  -- VoteId repeats per meeting; unique per (vote, item)
);

CREATE TABLE IF NOT EXISTS office_records (
  office_record_id            INTEGER PRIMARY KEY,
  person_id                   INTEGER REFERENCES persons(person_id),
  body_id                     INTEGER REFERENCES bodies(body_id),
  office_record_title         TEXT,   -- Council Member, Mayor, Mayor Pro Tem, etc.
  office_record_start_date    DATE,
  office_record_end_date      DATE,   -- null = currently serving
  office_record_member_type   TEXT,
  office_record_last_modified TIMESTAMPTZ
);

-- ---------------------------------------------------------------------------
-- Row Level Security — allow public read, block all writes via anon key
-- ---------------------------------------------------------------------------

ALTER TABLE bodies             ENABLE ROW LEVEL SECURITY;
ALTER TABLE persons            ENABLE ROW LEVEL SECURITY;
ALTER TABLE matters            ENABLE ROW LEVEL SECURITY;
ALTER TABLE events             ENABLE ROW LEVEL SECURITY;
ALTER TABLE matter_attachments ENABLE ROW LEVEL SECURITY;
ALTER TABLE event_items        ENABLE ROW LEVEL SECURITY;
ALTER TABLE votes              ENABLE ROW LEVEL SECURITY;
ALTER TABLE office_records     ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "public read" ON bodies;
DROP POLICY IF EXISTS "public read" ON persons;
DROP POLICY IF EXISTS "public read" ON matters;
DROP POLICY IF EXISTS "public read" ON events;
DROP POLICY IF EXISTS "public read" ON matter_attachments;
DROP POLICY IF EXISTS "public read" ON event_items;
DROP POLICY IF EXISTS "public read" ON votes;
DROP POLICY IF EXISTS "public read" ON office_records;

CREATE POLICY "public read" ON bodies             FOR SELECT USING (true);
CREATE POLICY "public read" ON persons            FOR SELECT USING (true);
CREATE POLICY "public read" ON matters            FOR SELECT USING (true);
CREATE POLICY "public read" ON events             FOR SELECT USING (true);
CREATE POLICY "public read" ON matter_attachments FOR SELECT USING (true);
CREATE POLICY "public read" ON event_items        FOR SELECT USING (true);
CREATE POLICY "public read" ON votes              FOR SELECT USING (true);
CREATE POLICY "public read" ON office_records     FOR SELECT USING (true);

-- ---------------------------------------------------------------------------
-- Transcription tables
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS transcripts (
  transcript_id       SERIAL PRIMARY KEY,
  event_id            INTEGER NOT NULL REFERENCES events(event_id),
  m3u8_url            TEXT,
  status              TEXT DEFAULT 'pending',  -- pending | processing | complete | error
  error_message       TEXT,
  duration_seconds    NUMERIC,
  cost_usd            NUMERIC,
  created_at          TIMESTAMPTZ DEFAULT now(),
  completed_at        TIMESTAMPTZ,
  UNIQUE (event_id)
);

CREATE TABLE IF NOT EXISTS transcript_segments (
  segment_id      BIGSERIAL PRIMARY KEY,
  transcript_id   INTEGER NOT NULL REFERENCES transcripts(transcript_id),
  event_id        INTEGER NOT NULL REFERENCES events(event_id),  -- denormalized for easy querying
  person_id       INTEGER REFERENCES persons(person_id),         -- null until speaker mapping
  speaker_label   TEXT NOT NULL,    -- e.g. "speaker_0"
  start_time      NUMERIC NOT NULL, -- decimal seconds
  end_time        NUMERIC NOT NULL,
  segment_text    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS speaker_mappings (
  mapping_id      SERIAL PRIMARY KEY,
  transcript_id   INTEGER NOT NULL REFERENCES transcripts(transcript_id),
  speaker_label   TEXT NOT NULL,
  person_id       INTEGER NOT NULL REFERENCES persons(person_id),
  UNIQUE (transcript_id, speaker_label)
);

ALTER TABLE transcripts          ENABLE ROW LEVEL SECURITY;
ALTER TABLE transcript_segments  ENABLE ROW LEVEL SECURITY;
ALTER TABLE speaker_mappings     ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "public read" ON transcripts;
DROP POLICY IF EXISTS "public read" ON transcript_segments;
DROP POLICY IF EXISTS "public read" ON speaker_mappings;

CREATE POLICY "public read" ON transcripts         FOR SELECT USING (true);
CREATE POLICY "public read" ON transcript_segments FOR SELECT USING (true);
CREATE POLICY "public read" ON speaker_mappings    FOR SELECT USING (true);

-- ---------------------------------------------------------------------------
-- Indexes for common query patterns
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_events_body_id        ON events(body_id);
CREATE INDEX IF NOT EXISTS idx_events_event_date      ON events(event_date);
CREATE INDEX IF NOT EXISTS idx_event_items_event_id   ON event_items(event_id);
CREATE INDEX IF NOT EXISTS idx_event_items_matter_id  ON event_items(matter_id);
CREATE INDEX IF NOT EXISTS idx_votes_person_id        ON votes(person_id);
CREATE INDEX IF NOT EXISTS idx_votes_event_item_id    ON votes(event_item_id);
CREATE INDEX IF NOT EXISTS idx_office_records_person  ON office_records(person_id);
CREATE INDEX IF NOT EXISTS idx_office_records_body    ON office_records(body_id);

CREATE INDEX IF NOT EXISTS idx_transcripts_event      ON transcripts(event_id);
CREATE INDEX IF NOT EXISTS idx_transcripts_status     ON transcripts(status);
CREATE INDEX IF NOT EXISTS idx_segments_transcript    ON transcript_segments(transcript_id);
CREATE INDEX IF NOT EXISTS idx_segments_event         ON transcript_segments(event_id);
CREATE INDEX IF NOT EXISTS idx_segments_person        ON transcript_segments(person_id);
