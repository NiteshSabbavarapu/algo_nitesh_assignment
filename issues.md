# Issues Found During Testing

I tried the migration flows using my own Polygon problem and went through the backend code to understand what happens at
each step. Here are the issues I found, ordered by priority.

## Product Issues

### [P1] Migration can report success even when tests are missing

**Problem:** Empty input or output test cases are silently skipped (`views.py:525`). Also, if tests are removed from
Polygon, their old records are not deleted from the database (`views.py:517-550`).

**Impact:** The migration can show success even when the database doesn't have the same tests as Polygon. This could
lead to publishing a problem with incorrect test cases.

**Suggested fix:** Sync tests using their index, delete records that no longer exist, and show how many tests were
actually saved. If something fails, report it instead of silently skipping it.

### [P2] Re-migration can delete existing data

**Problem:** When migrating a problem again, `migrate_to_storage` deletes the existing storage folder before uploading
the new files. It also overwrites the problem and clears its tags without asking for confirmation.

**Impact:** If the upload fails halfway through, the existing problem may be left without its test files.

**Suggested fix:** Ask for confirmation before overwriting existing data. Upload the new files first and remove the old
ones only after the upload succeeds.

### [P3] Migration steps and errors are not clear

**Problem:** Some button names don't really explain what happens. For example, "Migrate Test Cases to Azure" and
"Migrate Test Description to Database". Errors are also shown directly, such as `400 Bad Request` and
`Account URL must be a string`, without explaining what went wrong or how to fix it.

**Impact:** Someone using the tool for the first time may not know which step failed or what they need to do next.

**Suggested fix:** Use clearer button names, show the status of each migration step, and provide readable error messages
with possible solutions.

## Code Issues

### [C1] A single view handles too many things

**Problem:** One view file has around 480 lines and handles multiple responsibilities, including fetching data,
processing tests, database operations and migration logic.

**Impact:** It's difficult to understand the complete flow and make changes without affecting other parts of the
migration.

**Suggested fix:** Split the logic into smaller functions or service modules based on responsibility. Keep the views
focused on handling requests and responses.

### [C2] `PolygonAPI` handles too many responsibilities

**Problem:** The `PolygonAPI` class handles request signing, HTTP calls, Redis caching, compilation and uploading. These
responsibilities are mixed together.

I also found a cache invalidation issue:

- Cache clearing uses `oj_dev_with_redis_storage_test_cases_` (`line 691`).
- Cache writes use `polygon_migration_test_cases_` (`line 736`).

Because the prefixes don't match, clearing the cache doesn't remove the entries being written.

There are also no request timeouts.

**Impact:** This can result in stale test data and requests that keep waiting when Polygon doesn't respond.

**Suggested fix:** Separate the Polygon client, caching and compilation logic. Fix the cache key mismatch and add
timeouts to HTTP requests.

### [C3] No tests, and models are out of sync with migrations

**Problem:** The `tests.py` files are empty. I also found that `Problem.notes` exists in `models.py:79`, but the
corresponding migration was missing. This caused a fresh clone to fail when opening the first page.

**Impact:** There is no automated coverage for the migration flows, and a new developer cannot run the project cleanly
from scratch.

**Suggested fix:** Keep migrations in sync with the models, run `makemigrations --check` in CI, and add tests for
test-case parsing, database syncing and migration failures.

## Edge Cases

I traced these scenarios through the code. These are based on code inspection, not actual execution.

### Q1. What happens with 0 sample tests and 15 regular tests?

Nothing fails. No sample rows are created (`views.py:439-464`), and all 15 regular tests are saved and uploaded.

However, the tool doesn't show any warning that the problem has no sample tests.

### Q2. What happens if a problem has 20 tests, then 8 are removed from Polygon and it is migrated again?

The database still has all 20 records.

Only the first 12 records are updated. The remaining 8 are never deleted.

Storage behaves differently: the existing folder is cleared and the new 12 tests are uploaded.

So the final state is:

- Database: 20 tests
- Storage: 12 tests
- Polygon: 12 tests

The cache invalidation issue mentioned in C2 can also cause old test data to be used for up to 30 minutes.

### Q3. What information is lost when migrating test cases to the database?

Looking at `views.py:517-550`, I found that the following information is not preserved:

- Anything after the first 260 characters of the test description.
- Trailing whitespace is removed using `.rstrip()`.
- Tests with empty input or output are skipped.
- Polygon's test index and manual flag are not stored.

This means the database copy doesn't contain all the information needed to reconstruct or properly compare the original
problem. The complete data is only available in cloud storage.

## Changes Already Made

I also fixed two issues while going through the code:

1. Added the missing migration for `Problem.notes`, so fresh database setups no longer fail because