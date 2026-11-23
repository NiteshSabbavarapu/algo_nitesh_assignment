# How the Polygon Migration Tool Works

The Polygon Migration Tool is a Django application that fetches problems from Polygon, saves problem details and test
descriptions in PostgreSQL, and uploads complete test files to cloud storage.

Most of the functionality is handled by a single view, `problems/views.py`, inside the `index` function. All buttons
submit to `/` with a hidden field indicating the requested action.

## 1. Login

- The user logs in using email and password.
- `login_view` authenticates the user through the custom `EmailBackend`.
- Only staff users can access the migration tool.
- Successful login redirects to the Problem Migrator page.

## 2. Fetch Problem

- The user enters the Polygon problem ID and clicks Fetch Problem.
- The application connects to Polygon using the configured API credentials.
- It fetches the problem details, statement, limits, latest READY package, checker and test cases.
- The package is downloaded and its `problem.html` is parsed to extract the statement and formats.
- Test inputs and outputs are downloaded and cached in Redis for 30 minutes.
- Existing database details, such as tags and difficulty, are displayed when available.

This step only fetches data. It does not save anything to PostgreSQL.

## 3. Migrate Problem to Database

- The user selects a difficulty, adds tags and clicks Create/Update problem in Database.
- The application fetches the latest problem details from Polygon.
- It creates a new problem or updates the existing one using its Polygon ID.
- Tags and sample test cases are also saved.
- These database operations run inside a transaction.

**Tables involved:** `Problem`, `ProblemTag` and `SampleTestCase`.

## 4. Migrate Test Descriptions to Database

- The user clicks Migrate Test Description to Database.
- The application fetches the test cases from Polygon or Redis.
- It saves their inputs and outputs in `ProblemTestCase`.
- Inputs and outputs are trimmed and limited to 260 characters.

The database stores short test descriptions, not the complete test files.

## 5. Upload Test Cases to Cloud Storage

- The user clicks Migrate Test Cases to Azure (the UI label is outdated).
- The application gets the problem's database ID and initializes the configured storage provider.
- It deletes the existing test folder and uploads the latest test inputs and expected outputs.
- If the problem uses a custom checker, the application downloads its source, attempts to compile it with `g++`, and
  uploads the compiled file. If compilation fails, it uploads the source instead.

The storage provider is configurable through `STORAGE_PROVIDER`, supporting MinIO, S3, R2 and Azure.

## Where Data Is Stored

| Component     | Purpose                                                |
|---------------|--------------------------------------------------------|
| PostgreSQL    | Problem details, tags, samples and short test previews |
| Redis         | Cached Polygon test cases for 30 minutes               |
| Cloud storage | Complete test inputs, outputs and custom checker files |

Each problem gets a storage folder based on its database ID:

```text
test_cases/<db_id>/
    01
    01.a
    02
    02.a
    custom_checker
```

Each upload replaces the existing folder contents.

## Polygon API Integration

The application communicates with Polygon through signed POST requests to its API.

It uses methods such as `problem.info`, `problem.packages`, `problem.tests`, `problem.testInput`, `problem.testAnswer`
and `problem.checker`.

Requests are authenticated using `apiKey`, timestamp and an SHA-512-based signature generated using the API secret.

## Overall Flow

**Login → Fetch Problem → Save Problem Details → Save Test Descriptions → Upload Complete Test Files**

PostgreSQL stores the information needed by the application, Redis avoids repeated Polygon API calls, and cloud storage
holds the complete test files.