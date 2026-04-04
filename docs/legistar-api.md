# Legistar Web API Reference

Base URL: `https://webapi.legistar.com/v1/corpuschristi`

No authentication required for public data.

## Query Parameters (OData v3.0)

| Param | Example | Notes |
|-------|---------|-------|
| `$top` | `?$top=1000` | Limit results — **max 1,000 per request** |
| `$skip` | `?$skip=1000` | Offset for pagination |
| `$filter` | `?$filter=BodyActiveFlag eq 1` | Filter results |
| `$orderby` | `?$orderby=EventDate desc` | Sort — **only works on some fields; test before relying on it** |

**Pagination pattern:** Use `$top=1000&$skip=0`, then `$skip=1000`, `$skip=2000`, etc. Stop when fewer than 1,000 records are returned. Responses are plain JSON arrays — no metadata envelope.

**Incremental sync filter syntax:**
```
$filter=EventLastModifiedUtc gt datetime'2025-06-01T00:00:00'
```

---

## Endpoints & Response Schemas

All timestamps have a `*Utc` suffix and are ISO 8601 strings in UTC.
Fields ending in `Guid`, `RowVersion`, `Sort`, `Flag`, `Id` (non-primary) are generally internal metadata.

### GET /Bodies

```
/Bodies
/Bodies?$filter=BodyActiveFlag eq 1
```

| Field | Type | Notes |
|-------|------|-------|
| `BodyId` | number | Primary key |
| `BodyName` | string | e.g. "City Council" |
| `BodyTypeId` | number | Internal type ID |
| `BodyTypeName` | string | e.g. "Primary Legislative Body", "Department" |
| `BodyMeetFlag` | 0\|1 | Whether this body holds meetings |
| `BodyActiveFlag` | 0\|1 | Whether currently active |
| `BodyDescription` | string | Usually empty |
| `BodyContactNameId` | number\|null | |
| `BodyContactFullName` | string\|null | |
| `BodyContactPhone` | string\|null | |
| `BodyContactEmail` | string\|null | |
| `BodyNumberOfMembers` | number | |
| `BodyLastModifiedUtc` | string | ISO 8601 UTC |
| `BodyGuid` | string | Internal |
| `BodyRowVersion` | string | Internal |
| `BodySort` | number | Internal sort order |
| `BodyUsedControlFlag` | 0\|1 | Internal |
| `BodyUsedActingFlag` | 0\|1 | Internal |
| `BodyUsedTargetFlag` | 0\|1 | Internal |
| `BodyUsedSponsorFlag` | 0\|1 | Internal |

**Fields we store in Airtable:** `BodyId`, `BodyName`, `BodyTypeName` → BodyType, `BodyDescription`, `BodyActiveFlag`, `BodyLastModifiedUtc` → BodyLastModified
Note: API does not return `BodyMeetDay`, `BodyMeetTime`, or `BodyMeetLocation` — those are Airtable-only fields populated manually or from event patterns.

---

### GET /Events

```
/Events
/Events?$top=50&$skip=0
/Events?$filter=EventBodyId eq 138
```

| Field | Type | Notes |
|-------|------|-------|
| `EventId` | number | Primary key |
| `EventBodyId` | number | FK → Bodies |
| `EventBodyName` | string | Denormalized body name |
| `EventDate` | string | ISO 8601, time portion is always T00:00:00 |
| `EventTime` | string | e.g. "12:00 PM" — separate from EventDate |
| `EventLocation` | string | e.g. "Council Chambers" |
| `EventAgendaStatusId` | number | Internal |
| `EventAgendaStatusName` | string | e.g. "Final-revised", "Final", "Draft" |
| `EventMinutesStatusId` | number | Internal |
| `EventMinutesStatusName` | string | e.g. "Final-revised", "Final", "Draft" |
| `EventAgendaFile` | string\|null | URL to agenda PDF |
| `EventMinutesFile` | string\|null | URL to minutes PDF |
| `EventInSiteURL` | string | URL to Legistar meeting detail page |
| `EventVideoPath` | string\|null | URL to video recording |
| `EventVideoStatus` | string | e.g. "Public" |
| `EventMedia` | string\|null | Internal media ID |
| `EventComment` | string\|null | |
| `EventAgendaLastPublishedUTC` | string\|null | ISO 8601 UTC |
| `EventMinutesLastPublishedUTC` | string\|null | ISO 8601 UTC |
| `EventLastModifiedUtc` | string | ISO 8601 UTC |
| `EventItems` | array | Always `[]` at this endpoint — fetch separately |
| `EventGuid` | string | Internal |
| `EventRowVersion` | string | Internal |

**Fields we store in Airtable:** `EventId`, `EventBodyId` → Body (linked), `EventDate`, `EventTime`, `EventLocation`, `EventAgendaFile`, `EventMinutesFile`, `EventInSiteURL`, `EventVideoPath`, `EventMedia` → EventMedia (Granicus clip ID), `EventAgendaStatusName` → EventAgendaStatus, `EventMinutesStatusName` → EventMinutesStatus, `EventLastModifiedUtc` → EventLastModified

---

### GET /Events/{EventId}/EventItems

```
/Events/918/EventItems
/Events/918/EventItems?$top=50&$skip=0
```

| Field | Type | Notes |
|-------|------|-------|
| `EventItemId` | number | Primary key |
| `EventItemEventId` | number | FK → Events |
| `EventItemAgendaSequence` | number\|null | Order on the agenda |
| `EventItemMinutesSequence` | number\|null | Order in the minutes |
| `EventItemAgendaNumber` | string\|null | Display label, e.g. "A.", "1.", "B.2" |
| `EventItemTitle` | string | Description of the agenda item |
| `EventItemActionId` | number\|null | Internal |
| `EventItemActionName` | string\|null | e.g. "Approved", "Tabled" |
| `EventItemActionText` | string\|null | Full text of action taken |
| `EventItemPassedFlag` | 0\|1\|null | Whether item passed |
| `EventItemPassedFlagName` | string\|null | "Pass" or "Fail" |
| `EventItemAgendaNote` | string\|null | |
| `EventItemMinutesNote` | string\|null | |
| `EventItemMatterId` | number\|null | FK → Matters (null for procedural items) |
| `EventItemMatterGuid` | string\|null | Internal |
| `EventItemMatterFile` | string\|null | Denormalized matter file number |
| `EventItemMatterName` | string\|null | Denormalized matter name |
| `EventItemMatterType` | string\|null | Denormalized matter type |
| `EventItemMatterStatus` | string\|null | Denormalized matter status |
| `EventItemMatterAttachments` | array | Always `[]` here — fetch from Matters endpoint |
| `EventItemVideo` | number\|null | Internal video segment ID |
| `EventItemVideoIndex` | number\|null | Internal |
| `EventItemTally` | string\|null | Vote tally summary |
| `EventItemMoverId` | number\|null | PersonId who moved |
| `EventItemMover` | string\|null | Name of mover |
| `EventItemSeconderId` | number\|null | PersonId who seconded |
| `EventItemSeconder` | string\|null | Name of seconder |
| `EventItemRollCallFlag` | 0\|1 | Whether a roll call vote was taken |
| `EventItemConsent` | 0\|1 | Whether this is a consent agenda item |
| `EventItemLastModifiedUtc` | string | ISO 8601 UTC |
| `EventItemGuid` | string | Internal |
| `EventItemRowVersion` | string | Internal |
| `EventItemVersion` | string\|null | Internal |
| `EventItemFlagExtra` | number | Internal |
| `EventItemAccelaRecordId` | string\|null | Internal |

**Fields we store in Airtable:** `EventItemId`, `EventItemEventId` → Event (linked), `EventItemMatterId` → Matter (linked), `EventItemTitle`, `EventItemAgendaSequence` → EventItemAgendaNumber, `EventItemActionName`, `EventItemPassedFlagName` → EventItemResult, `EventItemAgendaNote`, `EventItemMinutesNote`, `EventItemLastModifiedUtc` → EventItemLastModified

---

### GET /Matters

```
/Matters
/Matters?$top=50&$skip=0
/Matters?$filter=MatterBodyId eq 138
```

| Field | Type | Notes |
|-------|------|-------|
| `MatterId` | number | Primary key |
| `MatterFile` | string | File number, e.g. "12-0046" |
| `MatterName` | string\|null | Short name/identifier |
| `MatterTitle` | string | Full title/description |
| `MatterTypeId` | number | Internal |
| `MatterTypeName` | string | e.g. "Resolution", "Ordinance" |
| `MatterStatusId` | number | Internal |
| `MatterStatusName` | string | e.g. "Passed", "Failed" |
| `MatterBodyId` | number | FK → Bodies |
| `MatterBodyName` | string | Denormalized body name |
| `MatterIntroDate` | string\|null | ISO 8601 |
| `MatterAgendaDate` | string\|null | ISO 8601 |
| `MatterPassedDate` | string\|null | ISO 8601 |
| `MatterEnactmentDate` | string\|null | ISO 8601 |
| `MatterEnactmentNumber` | string\|null | e.g. "029470" |
| `MatterRequester` | string\|null | Department or person requesting |
| `MatterNotes` | string\|null | |
| `MatterVersion` | string\|null | Version number |
| `MatterCost` | number\|null | |
| `MatterLastModifiedUtc` | string\|null | ISO 8601 UTC — **can be null** |
| `MatterReports` | array | Always `[]` here |
| `MatterText1`–`MatterText5` | string\|null | Custom text fields — unused for CC |
| `MatterDate1`–`MatterDate2` | string\|null | Custom date fields — unused for CC |
| `MatterEXText1`–`MatterEXText11` | string\|null | Extended custom fields — unused |
| `MatterEXDate1`–`MatterEXDate10` | string\|null | Extended custom date fields — unused |
| `MatterAgiloftId` | number | Internal |
| `MatterReference` | string\|null | |
| `MatterRestrictViewViaWeb` | boolean | |
| `MatterGuid` | string | Internal |
| `MatterRowVersion` | string | Internal |

**Fields we store in Airtable:** `MatterId`, `MatterFile`, `MatterName`, `MatterTitle`, `MatterTypeName` → MatterType, `MatterStatusName` → MatterStatus, `MatterBodyName`, `MatterIntroDate`, `MatterAgendaDate`, `MatterPassedDate`, `MatterEnactmentNumber`, `MatterLastModifiedUtc` → MatterLastModified

---

### GET /Matters/{MatterId}/Attachments

```
/Matters/1074/Attachments
```

| Field | Type | Notes |
|-------|------|-------|
| `MatterAttachmentId` | number | Primary key |
| `MatterAttachmentName` | string | Display name, e.g. "Staff Report" |
| `MatterAttachmentHyperlink` | string | Download URL |
| `MatterAttachmentFileName` | string | Filename |
| `MatterAttachmentMatterVersion` | string | Matter version this attachment belongs to |
| `MatterAttachmentIsHyperlink` | boolean | Whether it's a hyperlink vs uploaded file |
| `MatterAttachmentBinary` | null | Always null via API |
| `MatterAttachmentIsSupportingDocument` | boolean | |
| `MatterAttachmentShowOnInternetPage` | boolean | |
| `MatterAttachmentIsMinuteOrder` | boolean | |
| `MatterAttachmentIsBoardLetter` | boolean | |
| `MatterAttachmentDescription` | string\|null | |
| `MatterAttachmentPrintWithReports` | boolean | |
| `MatterAttachmentSort` | number | Display order |
| `MatterAttachmentAgiloftId` | number | Internal |
| `MatterAttachmentLastModifiedUtc` | string | ISO 8601 UTC |
| `MatterAttachmentGuid` | string | Internal |
| `MatterAttachmentRowVersion` | string | Internal |

**Fields we store in Airtable:** `MatterAttachmentId`, `MatterAttachmentName`, `MatterAttachmentHyperlink`, `MatterAttachmentIsSupportingDocument` → AttachmentIsSupporting, `MatterAttachmentLastModifiedUtc` → AttachmentLastModified
Note: `MatterId` is not returned in the response — it must be tracked from the parent request context.

---

### GET /Persons

```
/Persons
/Persons?$filter=PersonActiveFlag eq 1
```

| Field | Type | Notes |
|-------|------|-------|
| `PersonId` | number | Primary key |
| `PersonFirstName` | string | May be empty string |
| `PersonLastName` | string | |
| `PersonFullName` | string | e.g. "Nelda Martinez" |
| `PersonActiveFlag` | 0\|1 | |
| `PersonEmail` | string | May be an internal system email |
| `PersonPhone` | string | May be empty string |
| `PersonAddress1` | string | |
| `PersonCity1` | string | |
| `PersonState1` | string | |
| `PersonZip1` | string | |
| `PersonFax` | string | |
| `PersonWWW` | string | Website URL |
| `PersonAddress2` | string | Secondary address fields |
| `PersonCity2` | string | |
| `PersonState2` | string | |
| `PersonZip2` | string | |
| `PersonPhone2` | string | |
| `PersonFax2` | string | |
| `PersonEmail2` | string | |
| `PersonWWW2` | string | |
| `PersonLastModifiedUtc` | string | ISO 8601 UTC |
| `PersonGuid` | string | Internal |
| `PersonRowVersion` | string | Internal |
| `PersonCanViewFlag` | 0\|1 | Internal |
| `PersonUsedSponsorFlag` | 0\|1 | Internal |

**Fields we store in Airtable:** `PersonId`, `PersonFullName`, `PersonFirstName`, `PersonLastName`, `PersonEmail`, `PersonPhone`, `PersonActiveFlag`, `PersonLastModifiedUtc` → PersonLastModified

---

### GET /EventItems/{EventItemId}/Votes

```
/EventItems/13923/Votes
```

No top-level `/Votes` endpoint exists. Votes must be fetched per EventItem.

| Field | Type | Notes |
|-------|------|-------|
| `VoteId` | number | Primary key |
| `VoteEventItemId` | number | FK → EventItems |
| `VotePersonId` | number | FK → Persons |
| `VotePersonName` | string | Denormalized person name |
| `VoteValueId` | number | Internal |
| `VoteValueName` | string | e.g. "Aye", "Nay", "Absent" |
| `VoteResult` | 0\|1 | 1 = Pass, 0 = Fail (overall result of the item, not individual vote) |
| `VoteSort` | number | Display order |
| `VoteLastModifiedUtc` | string | ISO 8601 UTC |
| `VoteGuid` | string | Internal |
| `VoteRowVersion` | string | Internal |

**Fields we store in Airtable:** `VoteId`, `VoteEventItemId` → Event Item (linked), `VotePersonId` → Person (linked), `VotePersonName`, `VoteValueName`, `VoteResult` → VoteResult (1=Pass, 0=Fail), `VoteLastModifiedUtc` → VoteLastModified

---

### GET /OfficeRecords

```
/OfficeRecords
/OfficeRecords?$top=1000&$skip=0
```

| Field | Type | Notes |
|-------|------|-------|
| `OfficeRecordId` | number | Primary key |
| `OfficeRecordPersonId` | number | FK → Persons |
| `OfficeRecordFullName` | string | Denormalized person name |
| `OfficeRecordFirstName` | string | |
| `OfficeRecordLastName` | string | |
| `OfficeRecordEmail` | string | May be empty |
| `OfficeRecordBodyId` | number | FK → Bodies |
| `OfficeRecordBodyName` | string | Denormalized body name |
| `OfficeRecordTitle` | string | e.g. "Council Member", "Mayor", "City Manager" |
| `OfficeRecordStartDate` | string | ISO 8601 |
| `OfficeRecordEndDate` | string\|null | ISO 8601 — null if currently serving |
| `OfficeRecordMemberTypeId` | number | Internal |
| `OfficeRecordMemberType` | string | e.g. "Member" |
| `OfficeRecordSort` | number | Internal sort order |
| `OfficeRecordVoteDivider` | number | Internal |
| `OfficeRecordExtendFlag` | 0\|1 | Internal |
| `OfficeRecordSupportNameId` | number\|null | Internal |
| `OfficeRecordSupportFullName` | string\|null | Internal |
| `OfficeRecordExtraText` | string | Usually empty |
| `OfficeRecordLastModifiedUtc` | string | ISO 8601 UTC |
| `OfficeRecordGuid` | string | Internal |
| `OfficeRecordRowVersion` | string | Internal |

**Fields we store in Airtable:** `OfficeRecordId`, `OfficeRecordPersonId` → Person (linked), `OfficeRecordBodyId` → Body (linked), `OfficeRecordTitle`, `OfficeRecordStartDate`, `OfficeRecordEndDate`, `OfficeRecordMemberType`, `OfficeRecordLastModifiedUtc` → OfficeRecordLastModified

---

## Endpoint Summary

| Data | Endpoint | Sub-resource? |
|------|----------|---------------|
| Bodies | `GET /Bodies` | No |
| Events | `GET /Events` | No |
| Event Items | `GET /Events/{id}/EventItems` | Yes — requires EventId |
| Matters | `GET /Matters` | No |
| Matter Attachments | `GET /Matters/{id}/Attachments` | Yes — requires MatterId |
| Matter Histories | `GET /Matters/{id}/Histories` | Yes — requires MatterId |
| Persons | `GET /Persons` | No |
| Votes | `GET /EventItems/{id}/Votes` | Yes — requires EventItemId |
| Office Records | `GET /OfficeRecords` | No |
| Body Types | `GET /BodyTypes` | No — lookup table |
| Actions | `GET /Actions` | No — lookup table |

### EventItems inline expansion params

The EventItems endpoint supports query params to include related data inline (avoids separate calls for small datasets):
```
/Events/{id}/EventItems?AgendaNote=1&MinutesNote=1&Attachments=1
```
For large syncs, separate calls with pagination are more reliable.

## Known Quirks

- `$orderby` does **not** work on all fields — returns 400 if the field is not sortable. Test before relying on it. `$filter` and `$top`/`$skip` are reliable.
- `MatterLastModifiedUtc` **can be null** on older records.
- `EventItems` array on the `/Events` response is always `[]` — fetch items separately.
- `EventDate` includes a time component (`T00:00:00`) that should be ignored; actual time is in the separate `EventTime` string field.
- `PersonEmail` may contain internal system emails (e.g. Granicus addresses), not public contact emails.
- Votes have no top-level endpoint — you must iterate EventItems to collect votes.
- `MatterId` is not included in the Attachments response — track it from the parent loop.
