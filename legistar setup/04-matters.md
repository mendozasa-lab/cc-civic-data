# Create table: Matters

Create a table called "Matters" with the following fields:

1. **MatterId** — Number field (integer, no decimals). Unique identifier for each piece of legislation from the Legistar API.
2. **MatterFile** — Single line text. The file number assigned to this matter (e.g., "2025-0123").
3. **MatterName** — Single line text. Short name or identifier.
4. **MatterTitle** — Long text. The full title or description of the matter.
5. **MatterType** — Single select. Options: `Ordinance`, `Resolution`, `Presentation`, `Motion`, `Report`, `Agreement`, `Minutes`, `Other`.
6. **MatterStatus** — Single select. Options: `Introduced`, `Passed`, `Failed`, `Withdrawn`, `Tabled`, `Referred`, `Adopted`, `Other`.
7. **MatterBodyName** — Single line text. The name of the body that introduced this matter.
8. **MatterIntroDate** — Date field. The date the matter was introduced.
9. **MatterAgendaDate** — Date field. The date the matter appeared or will appear on an agenda.
10. **MatterPassedDate** — Date field. The date the matter was passed, if applicable.
11. **MatterEnactmentNumber** — Single line text. The enactment or ordinance number, if applicable.
12. **MatterLastModified** — Date field with time included. Last modified timestamp from the source system.

Do not create any linked record fields yet — those will be added later.
