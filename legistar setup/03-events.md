# Create table: Events

Create a table called "Events" with the following fields:

1. **EventId** — Number field (integer, no decimals). Unique identifier for each meeting from the Legistar API.
2. **Body** — Link to another record in the "Bodies" table. Each event belongs to one body. Allow linking to multiple records disabled (one body per event).
3. **EventDate** — Date field (no time). The date of the meeting.
4. **EventTime** — Single line text. The meeting start time as text (e.g., "11:30 AM").
5. **EventLocation** — Single line text. Where the meeting was held.
6. **EventAgendaFile** — URL field. Link to the agenda PDF.
7. **EventMinutesFile** — URL field. Link to the minutes PDF.
8. **EventInSiteURL** — URL field. Link to the meeting detail page on the Legistar website.
9. **EventVideoPath** — URL field. Link to the video recording.
10. **EventAgendaStatus** — Single select. Options: `Final`, `Draft`, `Not Available`.
11. **EventMinutesStatus** — Single select. Options: `Final`, `Draft`, `Not Available`.
12. **EventLastModified** — Date field with time included. Last modified timestamp from the source system.
