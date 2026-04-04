# Create table: Event Items

Create a table called "Event Items" with the following fields:

1. **EventItemId** — Number field (integer, no decimals). Unique identifier for each agenda line item from the Legistar API.
2. **Event** — Link to another record in the "Events" table. The meeting this item belongs to.
3. **Matter** — Link to another record in the "Matters" table. The piece of legislation this agenda item refers to, if any. This may be left empty for procedural items like roll call or adjournment.
4. **EventItemTitle** — Long text. The title or description of this agenda item.
5. **EventItemAgendaNumber** — Number field (integer). The item's position number on the agenda.
6. **EventItemActionName** — Single line text. The action taken (e.g., "Approved", "Tabled", "Received and Filed").
7. **EventItemResult** — Single select. Options: `Pass`, `Fail`, `Withdrawn`, `Tabled`, `Received and Filed`, `No Action`, `Other`.
8. **EventItemAgendaNote** — Long text. Notes from the agenda for this item.
9. **EventItemMinutesNote** — Long text. Notes from the minutes for this item.
10. **EventItemLastModified** — Date field with time included. Last modified timestamp from the source system.
