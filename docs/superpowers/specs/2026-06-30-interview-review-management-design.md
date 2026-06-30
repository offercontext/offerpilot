# Interview Review Management Design

Date: 2026-06-30
Branch: `codex/feat-interview-review-management`

## Summary

OfferPilot already has an `interview_notes` table, note APIs, CLI commands, a lightweight note form in application details, and basic AI tools for listing and adding notes. This feature turns that foundation into a complete interview review management workflow.

The first version adds a dedicated review workspace in the web UI, preserves quick review entry from an application detail drawer, and expands AI chat tools so users can create, query, edit, and delete interview review records through conversation. It does not change the database schema.

## Goals

- Add an independent "Reviews" view alongside the current board and calendar views.
- Let users create review records from the UI, either linked to an application or standalone.
- Let users search, filter, edit, and delete review records from the management view.
- Keep application detail reviews useful for fast per-application capture.
- Support AI chat operations for review create, query, update, and delete.
- Keep write operations protected by the existing chat confirmation flow.

## Non-Goals

- No database schema expansion in the first version.
- No structured scoring, tags, or knowledge-point taxonomy.
- No AI-generated review analysis dashboard beyond what the chat assistant can answer from existing records.
- No server-side search or pagination unless implementation reveals a clear need.

## User Experience

The web app adds a third main view option: Board, Calendar, and Reviews.

The Reviews view contains:

- A primary "New Review" action.
- Search over company, position, round, questions, reflection, and weak points.
- Filters for linked application, mood, and date range.
- A list of review cards showing company, position, round, date, mood, question summary, reflection summary, weak-point summary, and actions.
- Edit and delete actions per record.
- Empty states for no records and no search results.

Create and edit use the same drawer form:

- Linked application selector.
- Company and position fields, auto-filled when an application is selected.
- Round, date, and mood fields.
- Questions, self reflection, and difficulty points text areas.
- Save and cancel actions.

Application detail keeps a lightweight review section:

- Quick-add a review for the current application.
- Show recent reviews linked to that application.
- Allow editing and deletion through the same service path as the Reviews view.

## Data Model

The feature uses the existing `InterviewNote` model:

- `id`
- `application_id`
- `company`
- `position`
- `round`
- `date`
- `questions`
- `self_reflection`
- `difficulty_points`
- `mood`
- `created_at`

No migration is required. When `application_id` is provided and company or position is omitted, the backend fills missing fields from the application record.

## API Design

Existing endpoints remain:

- `GET /api/notes`
- `GET /api/applications/{id}/notes`
- `POST /api/applications/{id}/notes`
- `PUT /api/notes/{id}`
- `DELETE /api/notes/{id}`

Add one endpoint for standalone management creation:

- `POST /api/notes`

`POST /api/notes` accepts the same payload as application-scoped creation:

- Optional `application_id`
- Optional `company`
- Optional `position`
- Optional `round`
- Optional `date`
- Optional `questions`
- Optional `self_reflection`
- Optional `difficulty_points`
- Optional `mood`

Validation:

- A note must resolve to a non-empty company.
- If `application_id` is present and company or position is blank, the backend attempts to backfill from the application.
- If the application cannot be found and company is missing, the request fails with `400`.

Frontend filtering and search can be client-side in the first version because OfferPilot is local-first and expected review volume is modest.

## Frontend Implementation Shape

Add or update these frontend pieces:

- `web/src/services/notes.ts`
  - `listNotes()`
  - `listNotesByApp(appID)`
  - `createNote(appID, input)`
  - `createStandaloneNote(input)`
  - `updateNote(id, input)`
  - `deleteNote(id)`
- `web/src/components/ReviewManagementView.tsx`
  - Owns global listing, filters, search, and drawer state.
- `web/src/components/ReviewFormDrawer.tsx`
  - Shared create/edit form.
- `web/src/App.tsx`
  - Adds `reviews` to the main segmented view.
- `web/src/components/ApplicationDetail.tsx`
  - Reuses the shared note service and, where practical, the shared form behavior.

The UI should follow existing Ant Design patterns and keep the operational, local-workbench feel of OfferPilot.

## AI Chat Design

Expand the AI tool registry:

### `list_notes`

Keep it read-only. It lists review records, optionally filtered by `application_id`. The assistant can use the returned records to answer summary questions such as recent reviews, repeated weak points, or reviews for a specific application.

### `add_note`

Keep it as a write tool and expand supported fields:

- `application_id`
- `company`
- `position`
- `round`
- `date`
- `questions`
- `self_reflection`
- `difficulty_points`
- `mood`

When `application_id` is provided, missing company or position should be backfilled from the application.

### `update_note`

Add a write tool that updates a note by `id`. It supports the same editable fields as the UI. It should preserve fields that the model does not explicitly update.

### `delete_note`

Add a write tool that deletes a note by `id`.

All AI write tools continue to use the existing confirmation flow unless chat auto-approve is enabled.

Update suggested prompts in the chat panel to include review-specific examples:

- "Help me record the interview review I just finished."
- "Summarize weak points from my recent interview reviews."
- "Show reviews for this week's interviews."

## Error Handling

- UI create and update failures show Ant Design error messages.
- Delete uses confirmation before making the request.
- Empty API results render clear empty states.
- AI write failures are surfaced through the existing chat error path.
- AI update/delete calls fail clearly when the note ID does not exist.

## Testing Plan

Backend tests:

- `POST /api/notes` creates standalone notes.
- `POST /api/notes` backfills company and position when `application_id` is provided.
- `PUT /api/notes/{id}` updates full note fields.
- `DELETE /api/notes/{id}` removes a note.
- AI `add_note` supports complete fields and application backfill.
- AI `update_note` updates an existing note through the registry.
- AI `delete_note` deletes through the registry.

Frontend verification:

- `npm.cmd run build` passes.
- Reviews view lists records, filters, searches, creates, edits, and deletes.
- Application detail review entry remains functional.

Final verification:

- `go test ./...`
- `npm.cmd run build`

## Implementation Order

1. Add backend standalone note creation and tests.
2. Expand note service methods and types on the frontend.
3. Build shared review form drawer.
4. Build Reviews management view and wire it into `App.tsx`.
5. Refine application detail note handling around shared service behavior.
6. Expand AI note tools and tests.
7. Run final verification.
