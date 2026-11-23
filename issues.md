# Issues Found During Code Review

I went through the migration flow and identified the following issues, along with their impact.

### 1. Invalid error handler (`views.py:559`)

The error handler calls `api.delete_azure_blob()`, but this method does not exist. If a migration fails, the error
handler raises another exception and hides the original error, making debugging difficult.

### 2. Cache clearing uses the wrong key (`polygon_api.py:691`)

The cache-clearing logic uses an incorrect key prefix and the database ID instead of the Polygon problem ID. As a
result, old test cases remain in Redis and can be reused during migration.

### 3. Old test cases are never deleted (`views.py:517-550`)

The migration updates existing test rows by position and creates new rows when needed, but never removes extra rows. If
tests are deleted on Polygon, the old rows remain in the database.

### 4. Failed Polygon packages can be selected (`polygon_api.py:~162`)

The original code selected the latest package without checking its status. This could select a package that had failed
verification, resulting in a 400 error. This was fixed by selecting only packages with the `READY` state.

### 5. Missing database migration (`models.py:79`)

The `Problem` model contains a `notes` field, but the corresponding database migration was missing. Fresh database
setups could fail when accessing the application. This was fixed by adding the `0002` migration.

---
I did sme changes in the code base to resolve issues #4 and # 5

* I have Written a Storage File (problems/storage.py) to connect aws s3 to my codebase

Imporvements I can do in the code base -

### 1. Difficulty validation is missing (`views.py:129, 347`, `models.py:59`)

The API accepts difficulty directly from the POST request without validating it. Django's `choices` does not enforce
allowed values at the database level, so invalid values can be saved.

### 2. Test cases lack unique ordering (`models.py:104, 137`)

The `order` field is not unique, and Polygon's original test number is not stored. This can make test identification
unreliable when positions change.

### 3. Test count is stored separately (`models.py:73`)

`test_case_count` is maintained independently of the actual test rows. If the rows change without updating this field,
the stored count can become incorrect.

### 4. Sample test cases are stored in two places (`models.py`)

Samples are maintained in both the `SampleTestCase` table and the `is_sample` field in `ProblemTestCase`. Nothing keeps
them synchronized, which can lead to inconsistent sample data.

### 5. API requests have no timeout (`polygon_api.py:96, 187`)

The `requests.post` calls do not specify a timeout. If Polygon responds slowly or stops responding, requests can remain
blocked for an extended period.

### 6. Migration logic is too large and repetitive (`views.py:89-570`)

A single function handles multiple responsibilities, making it difficult to maintain. The Redis fallback logic is also
repeated in multiple places instead of being reused.