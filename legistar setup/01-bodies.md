# Create table: Bodies

Create a table called "Bodies" with the following fields:

1. **BodyId** — Number field (integer, no decimals). This is the unique identifier for each body from the Legistar API.
2. **BodyName** — Single line text. The display name of the body (e.g., "City Council", "Planning Commission").
3. **BodyType** — Single select. Options: `Legislative Body`, `Board`, `Commission`, `Committee`, `Corporation`, `Other`.
4. **BodyDescription** — Long text. A description or mission statement for the body.
5. **BodyActiveFlag** — Checkbox. Whether this body is currently active.
6. **BodyMeetDay** — Single line text. The typical day of the week the body meets (e.g., "Tuesday").
7. **BodyMeetTime** — Single line text. The typical meeting start time (e.g., "11:30 AM").
8. **BodyMeetLocation** — Single line text. The typical meeting location.
9. **BodyLastModified** — Date field with time included. The last modified timestamp from the source system.

Do not create any linked record fields yet — those will be added later.
