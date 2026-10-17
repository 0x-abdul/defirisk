# Public comparison and local watchlist

`/compare/` compares two to four distinct published protocol families. Each
column selects one surface; the URL stores the protocol/surface pairs for
sharing and browser history. Aliases, duplicates and unavailable protocols are
excluded; a removed surface falls back to the first published surface. The
comparison shows categories, factor statuses, severity-rated coverage, missing
factors, evidence summaries and their dates, review dates, rubric versions,
scope and deployment labels. It does not compute a combined grade, score or
ranking. Category severity uses the same model as the existing assessment UI.
Coverage includes the full rubric denominator and displays not-applicable,
pending, unknown and missing factors explicitly. It uses surface-wide evidence,
not deployment-specific overrides; use the protocol page for those details.

`/watchlist/` keeps at most 100 protocol IDs and read history in localStorage
under `defirisk-watchlist-v1`. Protocol detail pages also offer a watch button.
There are no accounts, outbound notifications, background polling or server-side
personal state. Blocked storage falls back to page-local state with a notice;
malformed or unsupported stored state produces an empty list with a notice.
Changes in other browser tabs reload the list. Removing an entry deletes its
read history; clearing browser storage removes the full list.

The digest consumes the same `buildJsonFeed(listGradeChanges())` data as the
existing public grade-change JSON Feed. It identifies unread events by feed ID,
so late-arriving events with older timestamps remain visible. Marking available
entries read retains at most 400 IDs per protocol and the committed snapshot
timestamp; older snapshots cannot move the stored date backwards. If a saved
protocol disappears, its ID and history remain visible with an unavailable
label and a remove control. A previously seen event outside the retained ID
window can appear unread again. The public feed is bounded to 200 events;
the digest does not claim complete history, current live status or coverage of
factor-only evidence updates. The snapshot date is always shown.

Both features read the committed public projection through existing loaders.
They do not query a database or import unpublished/private assessments. An empty public projection produces explicit unavailable states. Unit tests use explicitly invented fixtures reviewed for schema and
behavior only; fixtures are not copied into publication data.
