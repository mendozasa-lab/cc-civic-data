# Create table: Votes

Create a table called "Votes" with the following fields:

1. **VoteId** — Number field (integer, no decimals). Unique identifier for each individual vote from the Legistar API.
2. **Event Item** — Link to another record in the "Event Items" table. The agenda item this vote was cast on.
3. **Person** — Link to another record in the "Persons" table. The person who cast this vote.
4. **VotePersonName** — Single line text. The voter's name as recorded in the source system (kept as a backup in case the linked record isn't matched).
5. **VoteValueName** — Single select. Options: `Aye`, `Nay`, `Abstain`, `Absent`, `Recused`, `Present`.
6. **VoteResult** — Single select. The overall result of the vote on this item. Options: `Pass`, `Fail`.
7. **VoteLastModified** — Date field with time included. Last modified timestamp from the source system.
