# Create table: Matter Attachments

Create a table called "Matter Attachments" with the following fields:

1. **AttachmentId** — Number field (integer, no decimals). Unique identifier for each attachment from the Legistar API.
2. **Matter** — Link to another record in the "Matters" table. The matter this attachment belongs to.
3. **AttachmentName** — Single line text. The display name of the attachment (e.g., "Staff Report", "Ordinance Draft").
4. **AttachmentHyperlink** — URL field. The download link for the attachment file.
5. **AttachmentIsSupporting** — Checkbox. Whether this is a supporting document (as opposed to the primary document).
6. **AttachmentLastModified** — Date field with time included. Last modified timestamp from the source system.
