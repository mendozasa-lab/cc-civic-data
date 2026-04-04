# Create table: Transcripts

Create a table called "Transcripts" with the following fields:

1. **TranscriptId** — Autonumber field. Auto-generated unique identifier for each transcript.
2. **Event** — Link to another record in the "Events" table. The meeting this transcript belongs to. Each transcript is linked to exactly one event.
3. **YouTubeVideoId** — Single line text. The YouTube video ID for the meeting recording (e.g., "YMjQBKXCKjs").
4. **YouTubeURL** — Formula field. Formula: `IF({YouTubeVideoId}, "https://www.youtube.com/watch?v=" & {YouTubeVideoId}, "")`. Generates the full YouTube URL from the video ID.
5. **TranscriptSource** — Single select. How the transcript was generated. Options: `YouTube Auto-Captions`, `Whisper AI`, `AssemblyAI`, `Manual`, `Other`.
6. **TranscriptFullText** — Long text. The complete transcript text of the meeting.
7. **TranscriptStatus** — Single select. Options: `Pending`, `Complete`, `Failed`, `Needs Review`.
8. **TranscriptCreated** — Date field with time included. When the transcript was generated.
9. **TranscriptWordCount** — Formula field. Formula: `IF({TranscriptFullText}, LEN(SUBSTITUTE({TranscriptFullText}, " ", "x")) - LEN(SUBSTITUTE({TranscriptFullText}, " ", "")) + 1, 0)`. Approximate word count.
