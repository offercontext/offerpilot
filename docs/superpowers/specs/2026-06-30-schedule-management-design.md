# Schedule Management Design

## Goal

OfferPilot needs a first-class schedule management feature for job-search events. Users should be able to create written test, interview, and assessment events from the UI, see them on the calendar, and ask the AI assistant to create, query, update, or delete those events.

The first release deliberately keeps scope tight:

- Every schedule event must be linked to an existing application.
- Supported event types are `written_test`, `interview`, and `assessment`.
- Each event has a start datetime and duration in minutes.
- The calendar continues to show existing applied dates and interview retrospective notes, but only formal schedule events are editable/deletable as schedule items.

## Context

The codebase already has:

- A SQLite `events` table and `db.Event` type in `internal/db/db.go`.
- A calendar aggregation endpoint at `GET /api/calendar`.
- A React calendar view in `web/src/components/CalendarView.tsx`.
- An AI tool-calling registry in `internal/ai/tools.go` with write confirmation support.

The design should complete the existing `events` path instead of introducing a parallel `schedule_events` table.

## Data Model

Use the existing `events` table as the canonical schedule-event table.

Fields:

- `id`: event id.
- `application_id`: required foreign key to `applications(id)`.
- `event_type`: one of `written_test`, `interview`, `assessment`.
- `round`: optional integer round number, mainly for interviews.
- `scheduled_at`: required start datetime for first-class schedule events.
- `duration`: store a positive minute count as a string for compatibility with the existing schema, for example `"60"`.
- `location`: optional online/offline location or meeting link.
- `notes`: optional detail text.
- `created_at`: creation timestamp.

Validation rules:

- `application_id` must refer to an existing application.
- `event_type` must be one of the three supported values.
- `scheduled_at` is required and must parse as a datetime.
- `duration` must represent an integer greater than zero.
- Deleting an application should continue to cascade-delete its events.

## Backend API

Add `internal/db/events.go` with focused CRUD/query methods:

- `CreateEvent(event *db.Event) error`
- `GetEvent(id int64) (*db.Event, error)`
- `ListEvents(filter EventFilter) ([]EventWithApplication, error)`
- `ListEventsByApplication(applicationID int64) ([]EventWithApplication, error)`
- `UpdateEvent(event *db.Event) error`
- `DeleteEvent(id int64) error`

`EventWithApplication` should include application company and position fields so calendar and AI responses do not need N+1 application lookups.

Add `internal/api/events.go` and register routes in `internal/api/router.go`:

- `GET /api/events?month=YYYY-MM&application_id=&type=`
- `POST /api/events`
- `GET /api/events/{id}`
- `PUT /api/events/{id}`
- `DELETE /api/events/{id}`

Request/response bodies should expose `duration_minutes` as a number. The API layer converts that to/from the existing DB `duration` string.

Update `GET /api/calendar`:

- Include formal schedule events for the requested month.
- Keep existing applied-date and interview-note entries.
- Extend `CalendarEntry` with optional `event_id`, `event_type`, `scheduled_at`, `duration_minutes`, `location`, and `editable`.
- Set `editable=true` only for formal schedule events.

## Frontend UX

Use a dual-entry design with one shared form:

- Calendar page toolbar: add `新建日程`.
- Application detail drawer: add a `日程` section listing events for that application and an `安排日程` action.
- Both entry points reuse the same schedule-event form.
- When opened from application detail, the application is prefilled and locked.
- When opened from calendar, the user must select an application.

Form fields:

- Application selector, hidden/locked when prefilled.
- Event type: `笔试`, `面试`, `测评`.
- Start datetime.
- Duration in minutes.
- Optional round, location, notes.

Calendar behavior:

- Date cells show readable schedule chips where space allows: time, type, and company/position.
- Date drawer shows all entries for the day.
- Formal schedule events can be opened for edit/delete.
- Applied dates and interview retrospective notes remain view-only calendar entries.

Suggested frontend files:

- `web/src/types/event.ts`
- `web/src/services/events.ts`
- `web/src/components/ScheduleEventForm.tsx`
- updates to `CalendarView.tsx`, `ApplicationDetail.tsx`, and `types/calendar.ts`

## AI Assistant Tools

Extend `internal/ai/tools.go` with schedule tools:

- `list_events`: query by month, application, event type, or date range.
- `get_event`: fetch one event before update/delete if needed.
- `create_event`: create a schedule event.
- `update_event`: update type, datetime, duration, round, location, or notes.
- `delete_event`: delete a schedule event.

Write tools must keep using the existing confirmation flow.

Confirmation text examples:

- `为投递 #12 创建 2026-07-03 14:00 的面试日程，时长 60 分钟`
- `将日程 #5 改为 2026-07-04 10:00，时长 90 分钟`
- `删除日程 #5`

Prompt behavior:

- If the user mentions a company/position instead of an application id, the assistant should call `list_applications` first.
- If the application match is ambiguous, the assistant should ask a clarifying question before creating or modifying an event.
- If the user says relative dates like "明天", the assistant should resolve them using the current runtime date and preserve the exact scheduled datetime in the tool call.

## Error Handling

Backend:

- Return `400` for invalid event type, missing application, missing/invalid datetime, or non-positive duration.
- Return `404` for missing application or event.
- Return `500` only for unexpected storage errors.

Frontend:

- Surface API validation errors with Ant Design messages.
- Disable submit while creating/updating.
- Confirm destructive deletes.
- Refresh calendar, event lists, and application detail after mutations.

AI:

- Tool errors should be returned as tool results so the assistant can explain the problem and ask for corrected input.
- Write operations remain gated unless `chat_auto_approve_writes` is enabled.

## Testing

Backend tests:

- DB event create/get/list/update/delete.
- Month filtering and application filtering.
- Validation for event type, missing application, invalid datetime, and invalid duration.
- Calendar aggregation includes formal schedule events while preserving applied dates and notes.
- AI registry exposes event tools and write tools produce useful confirmation text.

API tests:

- Event CRUD happy paths.
- Validation error responses.
- Calendar response includes `event_id` and `editable=true` for formal events.

Frontend verification:

- Run `npm.cmd run build`.
- No new frontend test framework is required for the first release.

Project verification:

- Run `go test ./...`.
- Run `npm.cmd run build` from `web/`.
