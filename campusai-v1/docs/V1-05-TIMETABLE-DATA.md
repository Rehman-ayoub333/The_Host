# V1-05 — Timetable Data, Normalisation, and Extraction

Files covered: `backend/normalize.py`, `backend/data/timetable.json`, `backend/data/demo_data.json`, `scripts/extract_timetable.py`.

## 1. Principle

The real timetable PDF is converted **once, before the demo**, into `timetable.json`, checked by a human, and then used read-only. The running system **never reads the PDF**. Until the real file exists, the placeholder dataset in §5 is used; swapping it for real data changes **no code** (the schema and normalisation cover both).

## 2. `timetable.json` schema

A JSON array of objects, each with **all seven keys** (values are strings; `teacher`, `section`, and `room` may be empty strings if the source has none):

```json
{"course": "Data Structures", "teacher": "Dr. Ahmed", "day": "Monday",
 "start_time": "10:00", "end_time": "11:00", "room": "Lab 1", "section": "BSCS-6A"}
```
`day`, `start_time`, `end_time` may be written in any form `normalize.py` accepts; the loader normalises them. A row that lacks a key, or whose day/time cannot be normalised, is skipped and logged (`WARNING: skipped timetable row N: reason`). Zero valid rows → startup failure.

## 3. `normalize.py` (exact behaviour)

### 3.1 `normalize_day(s: str) -> str | None`
Lower-case and strip `s`; remove a trailing `.`, `,` or plural `s` if the result is not directly in the table; look up:

| Input forms | Result |
|---|---|
| `monday`, `mon` | `Monday` |
| `tuesday`, `tue`, `tues` | `Tuesday` |
| `wednesday`, `wed` | `Wednesday` |
| `thursday`, `thu`, `thur`, `thurs` | `Thursday` |
| `friday`, `fri` | `Friday` |
| `saturday`, `sat` | `Saturday` |
| `sunday`, `sun` | `Sunday` |

Anything else (including `today`, `tomorrow`) → `None` (the model resolves those words using the current date in its system instruction).
`DAY_ORDER = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]`.

### 3.2 `normalize_time(s: str) -> str | None`
Returns `"HH:MM"` (24-hour, zero-padded) or `None`.
1. `t = s.strip().lower()`.
2. Replace `a.m.`/`p.m.` (with or without trailing dot) by `am`/`pm` using `re.sub(r'\b([ap])\.m\.?', r'\1m', t)`; then replace any remaining `.` with `:`.
3. Remove the words `o'clock`, `oclock`, `sharp`, `hours`, `hrs`.
4. `noon` → `12:00`; `midnight` → `00:00`.
5. Match `^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$`. If it fails, try `^(\d{3,4})$` (e.g. `1400`, `930`): hour = all but last two digits, minute = last two. Otherwise → `None`.
6. `am`/`pm` handling: `pm` and hour < 12 → hour + 12; `am` and hour == 12 → hour = 0.
7. **Daytime assumption:** if there is no am/pm suffix and 1 ≤ hour ≤ 7 → hour + 12 (so `2:00` means 14:00; `8`–`12` stay as written).
8. Validate 0 ≤ hour ≤ 23 and 0 ≤ minute ≤ 59, else `None`.

| Input | Output |
|---|---|
| `10am`, `10 am`, `10:00`, `10` | `10:00` |
| `2pm`, `2 pm`, `2:00 pm`, `14:00`, `1400`, `2:00`, `2` | `14:00` |
| `2:30` | `14:30` |
| `12`, `noon` | `12:00` |
| `12am`, `midnight` | `00:00` |
| `9:05 a.m.` | `09:05` |
| `25:00`, `abc`, `` | `None` |

### 3.3 `normalize_room(s: str) -> str`
`re.sub(r"[\s\-_]+", "", s.strip().lower())`; then, if the result starts with `room` and is longer than 4 characters, remove that prefix. Empty input → `""`.
`Lab 3` → `lab3`; `lab-3` → `lab3`; `Room 12` → `12`; `room12` → `12`; `Seminar A` → `seminara`.

### 3.4 `time_in_range(t: str, start: str, end: str) -> bool`
`start <= t < end` using string comparison of zero-padded `"HH:MM"`. A class that ends exactly at `t` does **not** cover `t`.

### 3.5 `add_minutes(t: str, minutes: int) -> str`
Returns `"HH:MM"` for `t` plus `minutes`, capped at `"23:59"` (used for override windows).

## 4. Query semantics (`data.query_timetable_data`)

All provided filters are ANDed; omitted filters are ignored.

| Filter | Rule |
|---|---|
| `day` | canonical day of the entry equals `normalize_day(day)`; if `day` is provided but cannot be normalised → return `[]` |
| `time` | `time_in_range(normalize_time(time), entry._start, entry._end)`; unparseable → `[]` |
| `room` | `normalize_room(entry.room) == normalize_room(room)` (equality, so `Lab 1` never matches `Lab 10`) |
| `teacher` | case-insensitive substring of `entry.teacher` |
| `course` | case-insensitive substring of `entry.course` |

Results are sorted by `DAY_ORDER` index then `start_time`, and contain only the seven public fields with canonical `day` and normalised `HH:MM` times.

**Override windows:** an override in `room_overrides` covers the **one hour starting at its `time`** (`time <= t < add_minutes(time, 60)`) on its `day` for its room. `check_override` loads overrides for the normalised room and canonical day and tests each window.

## 5. Placeholder dataset (use until the real file exists)

`backend/data/timetable.json` — save exactly:
```json
[
  {"course": "Data Structures", "teacher": "Dr. Ahmed", "day": "Monday", "start_time": "10:00", "end_time": "11:00", "room": "Lab 1", "section": "BSCS-6A"},
  {"course": "Operating Systems", "teacher": "Dr. Bilal", "day": "Monday", "start_time": "11:00", "end_time": "12:00", "room": "Lab 3", "section": "BSCS-6A"},
  {"course": "Database Systems", "teacher": "Ms. Sadia", "day": "Monday", "start_time": "14:00", "end_time": "15:00", "room": "Lab 3", "section": "BSCS-6B"},
  {"course": "Artificial Intelligence", "teacher": "Dr. Ahmed", "day": "Tuesday", "start_time": "10:00", "end_time": "11:00", "room": "Seminar A", "section": "BSCS-6A"},
  {"course": "Software Engineering", "teacher": "Dr. Bilal", "day": "Tuesday", "start_time": "13:00", "end_time": "14:00", "room": "Lab 1", "section": "BSCS-6B"},
  {"course": "Computer Networks", "teacher": "Ms. Sadia", "day": "Wednesday", "start_time": "09:00", "end_time": "10:00", "room": "Seminar B", "section": "BSCS-6A"},
  {"course": "Web Engineering", "teacher": "Dr. Farah", "day": "Wednesday", "start_time": "11:00", "end_time": "12:00", "room": "Lab 2", "section": "BSCS-6B"},
  {"course": "Machine Learning", "teacher": "Dr. Ahmed", "day": "Thursday", "start_time": "14:00", "end_time": "15:00", "room": "Lab 2", "section": "BSCS-6A"},
  {"course": "Data Structures Lab", "teacher": "Mr. Usman", "day": "Friday", "start_time": "10:00", "end_time": "12:00", "room": "Lab 1", "section": "BSCS-6A"},
  {"course": "Technical Writing", "teacher": "Ms. Sadia", "day": "Friday", "start_time": "12:00", "end_time": "13:00", "room": "Seminar A", "section": "BSCS-6B"}
]
```
`backend/data/demo_data.json` — save exactly (rooms that the timetable shows as free, staged as unavailable for demonstration; overrides never contradict a real class):
```json
[
  {"room": "Lab 1", "day": "Monday", "time": "15:00", "available": false, "note": "reserved for a demo event"},
  {"room": "Seminar A", "day": "Tuesday", "time": "14:00", "available": false, "note": "reserved for a demo event"}
]
```
Facts the tests and demo rely on (placeholder data): Lab 2 is free all Monday → "free, from the timetable"; Lab 3 Monday 14:00 → booked by Database Systems; Lab 1 Monday 15:00 → booked by the demo override; Lab 4 → unknown room.

## 6. Extraction of the real timetable (one time, before the demo)

**Trigger:** when the real PDF is provided. **Output contract:** `backend/data/timetable.json` in the §2 schema. **Nothing else in the system changes.**

`scripts/extract_timetable.py` has its own dependencies in `scripts/requirements-extract.txt` (`pdfplumber`, `pymupdf`, `pillow`, `google-genai`), separate from the runtime requirements. Usage: `python scripts/extract_timetable.py path/to/timetable.pdf`.

**Step 0 — inspect first.** Open the PDF and write `docs/timetable-extraction-notes.md` (5–10 lines): is the text selectable; is the layout a flat list or a grid (e.g. days × periods with cells like "Course – Teacher – Room"); how rooms/sections are shown. The script is written to match what is actually there.

**Decision procedure (fixed):**
1. Try `pdfplumber`: if the concatenated `page.extract_text()` of all pages has ≥ 200 characters → **text path**: use `page.extract_tables()`, convert every cell that holds a class into one row per class occurrence (a grid becomes many flat rows; a cell spanning several periods becomes one row with the right `start_time`/`end_time`). Rows are written using the raw strings found; the loader normalises them.
2. Otherwise → **vision path** (scanned/image PDF): render each page to PNG at 200 DPI with PyMuPDF; send each image to a Gemini Flash model (env `EXTRACTION_MODEL`, default `gemini-2.5-flash`; confirm it exists in your model list) with this fixed prompt, and parse the JSON reply:
   > "This image is a university class timetable. Return ONLY a JSON array where each element is one class occurrence with exactly these string keys: course, teacher, day, start_time, end_time, room, section. Use an empty string when a value is not shown. Do not invent data. If a cell spans several periods, give the real start and end time."
3. Merge pages, drop exact duplicates, write `backend/data/timetable.json`.
4. Print: row count, count per day, and the **full table** (one line per row) to the console.

**Mandatory human verification (no exceptions, for both paths):** the operator compares the printed table with the PDF row by row and corrects mistakes by editing the JSON by hand. Automated extraction — especially OCR/vision — is treated as a draft. The build is not considered finished until this is signed off in the day report.

**Acceptance for the swap:** after replacing the placeholder file: backend starts; `GET /health` shows the new row count; TC-08 to TC-12 (V1-11) are re-run using three real entries the operator picks; `pytest` still passes (tests use their own fixture data, not this file).
