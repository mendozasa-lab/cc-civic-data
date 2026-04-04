# Airtable Scripting API Reference

Source: https://airtable.com/developers/scripting

## Global Variables

| Global | Available In |
|--------|-------------|
| `base` | Extension + Automation |
| `table` | Automation only (the table that triggered the automation) |
| `cursor` | Extension only |
| `session` | Extension only |
| `input` | Extension + Automation (different methods — see below) |
| `output` | Extension + Automation (different methods — see below) |

---

## base

```js
base.id               // string
base.name             // string
base.tables           // Array<Table>
base.activeCollaborators  // Array<Collaborator>

base.getTable(idOrName)        // => Table
base.getCollaborator(idOrNameOrEmail)  // => Collaborator

// Scripting Extension only
await base.createTableAsync(name, fields)  // => string (table ID)
```

**`createTableAsync` field array format:**
```js
{ name: string, type: FieldType, options?: object, description?: string }
```
- First field in array becomes the primary field (must be a supported primary type)
- Returns the new table's ID as a string (not a Table object)

---

## table

```js
table.id           // string
table.name         // string
table.description  // string | null
table.url          // string
table.fields       // Array<Field>
table.views        // Array<View>

table.getField(idOrName)  // => Field
table.getView(idOrName)   // => View

// Scripting Extension only
await table.createFieldAsync(name, type, options?, description?)  // => string (field ID)

// Extension + Automation
await table.selectRecordsAsync(options?)     // => RecordQueryResult
await table.selectRecordAsync(recordId, options?)  // => Record | null
await table.createRecordAsync(fields)        // => string (record ID)
await table.createRecordsAsync(records)      // => Array<string> (record IDs) — max 50
await table.updateRecordAsync(recordOrId, fields)   // => void
await table.updateRecordsAsync(records)      // => void — max 50
await table.deleteRecordAsync(recordOrId)    // => void
await table.deleteRecordsAsync(recordsOrIds) // => void — max 50
```

**`selectRecordsAsync` options:**
```js
{
  sorts?: Array<{ field: Field | string, direction?: 'asc' | 'desc' }>,
  fields?: Array<Field | string>,  // recommended — only load what you need
  recordIds?: Array<string>,       // max 100
}
```

---

## view

```js
view.id    // string
view.name  // string
view.type  // 'grid' | 'form' | 'calendar' | 'gallery' | 'kanban'
view.url   // string

// Extension + Automation (default sort follows view's UI order, unlike table.selectRecordsAsync)
await view.selectRecordsAsync(options?)    // => RecordQueryResult
await view.selectRecordAsync(recordId, options?)  // => Record | null
```

---

## field

```js
field.id          // string
field.name        // string
field.description // string | null
field.type        // FieldType string (see Field Types section)
field.options     // null | object (shape depends on type)
field.isComputed  // boolean — true for formula, autoNumber, rollup, etc.

await field.updateDescriptionAsync(description)  // => void  [Extension + Automation]

// Scripting Extension only
await field.updateOptionsAsync(options)  // => void
await field.updateNameAsync(name)        // => void
```

---

## RecordQueryResult

```js
result.records    // Array<Record>
result.recordIds  // Array<string>
result.getRecord(recordId)  // => Record (throws if not found)
```

---

## record

```js
record.id    // string
record.name  // string — primary field value, or 'Unnamed record' if empty

record.getCellValue(fieldOrIdOrName)         // => typed value (see Field Types)
record.getCellValueAsString(fieldOrIdOrName) // => string (always safe)
```

---

## cursor (Scripting Extension only)

```js
cursor.activeTableId  // TableId | null
cursor.activeViewId   // ViewId | null
```

---

## session (Scripting Extension only)

```js
session.currentUser  // Collaborator | null (null in publicly shared bases)
```

---

## collaborator

```js
collaborator.id           // string
collaborator.name         // string | null
collaborator.email        // string
collaborator.profilePicUrl // string | null
```

---

## input

### Scripting Extension only

```js
await input.textAsync(label)                        // => string
await input.buttonsAsync(label, options)            // => string | value
await input.tableAsync(label)                       // => Table
await input.viewAsync(label, tableOrIdOrName)       // => View
await input.fieldAsync(label, tableOrIdOrName)      // => Field
await input.recordAsync(label, source, options?)    // => Record | null
await input.fileAsync(label, options?)              // => { file: File, parsedContents: any }

// Persistent settings UI — call once at top of script
const config = input.config({
  title: string,
  description?: string,
  items?: Array<SettingsItem>
})
// Settings item helpers:
input.config.table(key, options?)
input.config.field(key, { parentTable: string, ...options })  // parentTable = key of a table setting
input.config.view(key, { parentTable: string, ...options })
input.config.text(key, options?)
input.config.number(key, options?)
input.config.select(key, { options: Array<{value: string, label?: string}>, ...options })
```

### Automations only

```js
const cfg = input.config()       // => object — all pre-configured input key/value pairs
const val = input.secret('Key')  // => string — access a secret by name
```

---

## output

### Scripting Extension only

```js
output.text(source)       // display text
output.markdown(source)   // display markdown
output.table(data)        // display array/object as table
output.inspect(object)    // interactive explorer (good for debugging)
output.clear()            // clear all previous output
```

### Automations only

```js
output.set(key, value)  // pass JSON-serializable value to subsequent automation steps
```

---

## fetch

```js
// Extension + Automation
const response = await fetch(url, init?)

// Scripting Extension only — makes request from Airtable's servers (bypasses CORS)
const response = await remoteFetchAsync(url, init?)
```

**Automation fetch limitations vs browser:**
- No cookies (`credentials` option ignored, always `omit`)
- No redirect follow (only `error` and `manual` modes)
- No streaming
- No caching
- No CORS restrictions (runs server-side)
- 4.5MB response size limit
- No FormData support

---

## Field Types

### All valid field type strings

```
singleLineText | email | url | multilineText | number | percent | currency |
singleSelect | multipleSelects | singleCollaborator | multipleCollaborators |
multipleRecordLinks | date | dateTime | phoneNumber | multipleAttachments |
checkbox | formula | createdTime | rollup | count | multipleLookupValues |
autoNumber | barcode | rating | richText | duration | lastModifiedTime |
externalSyncSource
```

### Field types that CANNOT be created via script

```
formula | createdTime | rollup | count | multipleLookupValues | autoNumber |
lastModifiedTime | button | createdBy | lastModifiedBy | externalSyncSource | aiText
```

### Options schemas for creatable field types

**`singleLineText`, `email`, `url`, `multilineText`, `phoneNumber`, `richText`**
No options required.

**`number`**
```js
{ precision: number }  // 0–8; use 0 for integers
```

**`percent`**
```js
{ precision: number }  // 0–8
```

**`currency`**
```js
{ precision: number, symbol: string }  // precision 0–7
```

**`checkbox`**
```js
{
  icon: 'check' | 'star' | 'heart' | 'thumbsUp' | 'flag' | 'dot',
  color: 'yellowBright' | 'orangeBright' | 'redBright' | 'pinkBright' | 'purpleBright' |
         'blueBright' | 'cyanBright' | 'tealBright' | 'greenBright' | 'grayBright'
}
// Free/Plus plans: limited to icon 'check' and color 'greenBright'
```

**`singleSelect`**
```js
{
  choices: Array<{ name: string, color?: string }>  // color optional on creation
}
```

**`multipleSelects`** — same options format as `singleSelect`

**`date`**
```js
{
  dateFormat: { name: 'local' | 'friendly' | 'us' | 'european' | 'iso' }
  // format string is optional and must match name if provided:
  // local='l', friendly='LL', us='M/D/YYYY', european='D/M/YYYY', iso='YYYY-MM-DD'
}
```

**`dateTime`**
```js
{
  dateFormat: { name: 'local' | 'friendly' | 'us' | 'european' | 'iso' },
  timeFormat: { name: '12hour' | '24hour' },
  timeZone: string  // IANA timezone, e.g. 'America/Chicago', or 'utc' | 'client'
}
```

**`multipleRecordLinks`**
```js
// Write format (creation):
{ linkedTableId: string, viewIdForRecordSelection?: string }
// Note: prefersSingleRecordLink cannot be set programmatically (always false)
// Updating options for existing linked record fields is NOT supported
```

**`rating`**
```js
{
  icon: 'star' | 'heart' | 'thumbsUp' | 'flag' | 'dot',
  max: number,   // 1–10
  color: string  // same color options as checkbox
}
// Free/Plus plans: limited to icon 'star' and color 'yellowBright'
```

**`duration`**
```js
{ durationFormat: 'h:mm' | 'h:mm:ss' | 'h:mm:ss.S' | 'h:mm:ss.SS' | 'h:mm:ss.SSS' }
```

**`barcode`, `multipleAttachments`, `singleCollaborator`, `multipleCollaborators`**
No options required on creation.

### Cell value formats (read)

| Type | Read format |
|------|-------------|
| `singleLineText`, `email`, `url`, `multilineText`, `phoneNumber`, `richText` | `string` |
| `number`, `percent`, `currency`, `rating`, `duration`, `autoNumber`, `count` | `number` |
| `checkbox` | `true \| null` |
| `date`, `dateTime`, `createdTime`, `lastModifiedTime` | ISO 8601 string |
| `singleSelect` | `{ id, name, color? }` |
| `multipleSelects` | `Array<{ id, name, color? }>` |
| `multipleRecordLinks` | `Array<{ id, name }>` |
| `singleCollaborator`, `createdBy`, `lastModifiedBy` | `{ id, email, name?, profilePicUrl? }` |
| `multipleCollaborators` | `Array<{ id, email, name?, profilePicUrl? }>` |
| `multipleAttachments` | `Array<{ id, url, filename, size?, type?, thumbnails? }>` |
| `formula`, `rollup`, `multipleLookupValues` | varies — check `field.options.result.type` |
| `barcode` | `{ text, type? }` |
| `aiText` | `{ state, value, isStale, errorType? }` |
