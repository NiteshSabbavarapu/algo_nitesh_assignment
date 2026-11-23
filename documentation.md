# How the Polygon Migration Tool Works

The tool copies a problem from Polygon into our database, then uploads its test files to cloud storage. It's a Django
app. Almost everything happens in one page and one view: `problems/views.py`, function `index`. Every button on the page
posts to `/`, with a hidden field that says what to do (`migrate_to_db`, `migrate_test_cases_to_db` or
`migrate_to_azure`). A plain Fetch has none of them.

Where things are stored:

- **PostgreSQL**: the problem, tags, sample tests, and short previews of the test cases.
- **Redis**: downloaded test cases, kept for 30 minutes so we don't call Polygon again on every click.
- **Cloud storage** (I used MinIO): the full test files.

One thing to know: every button first runs the same "fetch from Polygon" code from flow 2, and only then does its own
job.

---

## 1. Login

- **User does:** opens `/users/login/`, enters email and password, clicks Login.
- **Sent:** a form post with `email` and `password` (plus the CSRF token).
- **Backend** (`users/views.py`, `login_view`): checks the email and password with `authenticate()` (our `EmailBackend`
  in `users/backends.py`). If it's wrong, "Invalid email or password." If the user isn't staff, "You do not have staff
  access." Otherwise it logs them in and redirects to the tool. If you open the login page while already logged in, it
  logs you out first.
- **External calls:** none.
- **Database:** reads the user table, writes a session.
- **User sees:** the Problem Migrator page, or a red message.

The tool page itself only allows logged-in staff (`@user_passes_test` on `index`).

## 2. Fetching a problem

- **User does:** types the Polygon problem ID (the `id=` in Polygon's sidebar, not the package number) and clicks Fetch
  Problem.
- **Sent:** a post to `/` with `problem_id`.
- **Backend**, in order:
    1. Creates `PolygonAPI()` with the key and secret from settings.
    2. If the problem is already in our database, it loads the saved tags and difficulty, and fetches the main solution.
       For a new problem the solution is not fetched on this first fetch. It shows up after the first "Create/Update
       problem in Database".
    3. Gets the name and limits (`problem.info`).
    4. Downloads the latest READY package (`problem.packages`, then `problem.package`), unzips it, and reads
       `problem.html` to get the title, statement, and input and output format (`parse_problem_html`).
    5. Downloads all test cases: `problem.tests`, then `problem.testInput` and `problem.testAnswer` for each test. They
       go into Redis for 30 minutes.
    6. Gets the checker (`problem.checker`). Known standard checkers keep their name, anything else is `custom`.
    7. Counts the tests and makes the slug from the title.
- **Database:** only reads. Nothing is saved to PostgreSQL.
- **User sees:** the problem details, statement, test table and main solution. Errors show in a red box.

## 3. Migrating the problem to the database

- **User does:** picks a difficulty, adds tags, clicks **Create/Update problem in Database**.
- **Sent:** `problem_id`, `migrate_to_db=1`, `difficulty`, and the tags.
- **Backend:**
    1. Runs the fetch from flow 2.
    2. Stops if no difficulty was chosen.
    3. Finds the problem by `polygon_id`. If it exists it overwrites the fields (title, slug, statement, limits,
       checker, notes). Otherwise it creates it.
    4. Clears the problem's tags and adds the selected ones (new tags are created).
    5. Saves the sample tests (the ones Polygon marks as samples) into `SampleTestCase`. Existing rows are updated by
       position.
- **Database writes:** `Problem`, `ProblemTag` and the link between them, `SampleTestCase`. It's all in one transaction.
- **User sees:** "Problem ... created in database successfully", plus the database ID and the Algopath link.

## 4. Migrating test cases to the database

In the page this button is called **Migrate Test Description to Database**.

- **User does:** clicks it (disabled until the problem is in the database).
- **Sent:** `problem_id` and `migrate_test_cases_to_db=1`.
- **Backend:** runs the fetch from flow 2, then goes through every test. It strips trailing whitespace, skips tests with
  an empty input or output, **cuts input and output to the first 260 characters**, and saves each as a
  `ProblemTestCase`. Rows are updated by position, or created if there are none.
- **Database writes:** `ProblemTestCase`.
- **User sees:** "Test cases description migrated to database Successfully."

So the database only holds short previews, not the real test files.

## 5. Uploading test cases to cloud storage

In the page this is the green **Migrate Test Cases to Azure** button. The label is old: it uploads to whichever storage
is set up.

- **User does:** clicks it (disabled until the problem is in the database).
- **Sent:** `problem_id` and `migrate_to_azure=1`.
- **Backend:**
    1. Gets the database ID of the problem. The storage folder uses this ID, not the Polygon ID.
    2. `get_storage()` (`problems/storage.py`) reads `STORAGE_PROVIDER` and the credentials from environment variables.
    3. `migrate_to_storage` gets the tests (Redis or Polygon), **deletes everything** in the problem's folder, then
       uploads each test's input and output. Tests with an empty input or output are skipped.
    4. If the problem has a custom checker, it downloads the source (`problem.viewFile`), compiles it with `g++`, and
       uploads it. If compiling fails, it uploads the source file instead.
- **Storage:** deletes and writes files in the bucket.
- **User sees:** "Test cases migrated to cloud storage successfully."

The difference between the two saves: the database keeps the problem and short previews for the app, and storage keeps
the complete test files.

---

## Polygon API

Every call is a POST to `https://polygon.codeforces.com/api/<method>`. Methods used: `problem.info`, `problem.packages`,
`problem.package`, `problem.tests`, `problem.testInput`, `problem.testAnswer`, `problem.checker`, `problem.viewFile`,
`problem.solutions`, `problem.viewSolution`, `problem.updateWorkingCopy`.

**Signing** (`_generate_api_sig` in `problems/polygon_api.py`): each request sends `apiKey`, `time` and `apiSig`. To
build `apiSig`, the params (including `apiKey` and `time`) are sorted and URL-encoded, then SHA-512 is taken of
`<6 random characters>/<method>?<params>#<secret>`. The signature is those 6 characters plus the hash. The secret is
never sent.

## Cloud storage

`STORAGE_PROVIDER` can be `minio`, `s3`, `r2` or `azure`. Each one reads its own environment variables (for MinIO:
`MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET_NAME`). The migration code only talks to a small
`StorageBackend` interface, so switching provider is just a settings change.

Each problem gets one folder named with its database ID:

```
test_cases/<db_id>/01            input of test 1
test_cases/<db_id>/01.a          answer of test 1
test_cases/<db_id>/02, 02.a ...
test_cases/<db_id>/custom_checker       compiled checker (if any)
test_cases/<db_id>/custom_checker.cpp   source (only if compiling failed)
```

Test numbers start at 1 and have two digits. Each upload deletes the folder first, so it always matches the last run.

---