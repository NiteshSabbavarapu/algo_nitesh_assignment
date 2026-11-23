"""
Storage abstraction for test-case files.

The migration flow only talks to ``StorageBackend``. Provider-specific code lives
in the concrete classes below, and ``get_storage()`` picks one based on the
``STORAGE_PROVIDER`` environment variable.

Object layout (unchanged from the original Azure implementation)::

    test_cases/{problem_id}/{test_number:02d}      # input file
    test_cases/{problem_id}/{test_number:02d}.a    # output file
    test_cases/{problem_id}/custom_checker[.exe|.cpp]

Supported providers:
    azure  - Azure Blob Storage (original implementation)
    s3     - AWS S3
    r2     - Cloudflare R2 (S3-compatible)
    minio  - MinIO or any other S3-compatible server
"""
import logging
import os
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class StorageConfigError(Exception):
    """Raised when required storage environment variables are missing."""


class StorageBackend(ABC):
    """Minimal interface the migration flow depends on."""

    @abstractmethod
    def put_object(self, key, data):
        """Store ``data`` (bytes) at ``key``, overwriting any existing object."""

    @abstractmethod
    def delete_prefix(self, prefix):
        """Delete every object whose key starts with ``prefix``. Returns the count."""

    @abstractmethod
    def list_keys(self, prefix):
        """Return all object keys starting with ``prefix``."""

    @abstractmethod
    def get_object(self, key):
        """Return the bytes stored at ``key``."""

    # ----- shared helpers built on the primitives above -----

    @staticmethod
    def test_case_keys(problem_id, test_number):
        base = f"test_cases/{problem_id}/{test_number:02d}"
        return base, f"{base}.a"

    def upload_test_case(self, problem_id, test_number, input_data, output_data):
        input_key, output_key = self.test_case_keys(problem_id, test_number)
        self.put_object(input_key, input_data.encode("utf-8"))
        self.put_object(output_key, output_data.encode("utf-8"))
        logger.info("Uploaded test #%s to %s and %s", test_number, input_key, output_key)

    def empty_problem(self, problem_id):
        deleted = self.delete_prefix(f"test_cases/{problem_id}/")
        logger.info("Deleted %d objects for problem %s", deleted, problem_id)
        return deleted

    def upload_checker(self, problem_id, filename, data):
        self.put_object(f"test_cases/{problem_id}/{filename}", data)


class S3Storage(StorageBackend):
    """Works with AWS S3, Cloudflare R2 and MinIO (anything speaking the S3 API)."""

    def __init__(self, bucket, access_key, secret_key, region=None, endpoint_url=None):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            endpoint_url=endpoint_url,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def put_object(self, key, data):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)

    def get_object(self, key):
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def list_keys(self, prefix):
        keys = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
        return keys

    def delete_prefix(self, prefix):
        keys = self.list_keys(prefix)
        for i in range(0, len(keys), 1000):  # S3 allows 1000 keys per delete call
            batch = [{"Key": k} for k in keys[i:i + 1000]]
            self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": batch})
        return len(keys)


class AzureStorage(StorageBackend):
    """Azure Blob Storage, wrapping the original AzureBlobManager credentials flow."""

    def __init__(self, container, account_url, tenant_id, client_id, username, password):
        from problems.AzureTestcase import AzureBlobManager

        self.container = container
        self._manager = AzureBlobManager(account_url, tenant_id, client_id, username, password)
        self._service = self._manager.blob_service_client

    def put_object(self, key, data):
        self._service.get_blob_client(container=self.container, blob=key).upload_blob(data, overwrite=True)

    def get_object(self, key):
        return self._service.get_blob_client(container=self.container, blob=key).download_blob().readall()

    def list_keys(self, prefix):
        client = self._service.get_container_client(self.container)
        return [b.name for b in client.list_blobs(name_starts_with=prefix)]

    def delete_prefix(self, prefix):
        client = self._service.get_container_client(self.container)
        keys = self.list_keys(prefix)
        for key in keys:
            client.delete_blob(key)
        return len(keys)


def _require(env, *names):
    missing = [n for n in names if not env.get(n)]
    if missing:
        raise StorageConfigError("Missing environment variables: " + ", ".join(missing))
    return [env[n] for n in names]


def get_storage(env=None):
    """Build the configured storage backend from environment variables."""
    env = os.environ if env is None else env
    provider = (env.get("STORAGE_PROVIDER") or "azure").strip().lower()

    if provider == "azure":
        url, tenant, client, user, pwd, container = _require(
            env, "AZURE_STORAGE_ACCOUNT_URL", "AZURE_TENANT_ID", "AZURE_CLIENT_ID",
            "AZURE_USERNAME", "AZURE_PASSWORD", "AZURE_CONTAINER_NAME")
        return AzureStorage(container, url, tenant, client, user, pwd)

    if provider == "s3":
        key, secret, bucket = _require(env, "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_S3_BUCKET_NAME")
        return S3Storage(bucket, key, secret, region=env.get("AWS_REGION") or "us-east-1")

    if provider == "r2":
        account, key, secret, bucket = _require(
            env, "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME")
        return S3Storage(bucket, key, secret, region="auto",
                         endpoint_url=f"https://{account}.r2.cloudflarestorage.com")

    if provider == "minio":
        endpoint, key, secret, bucket = _require(
            env, "MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "MINIO_BUCKET_NAME")
        secure = (env.get("MINIO_SECURE") or "False").strip().lower() == "true"
        scheme = "https" if secure else "http"
        return S3Storage(bucket, key, secret, region="us-east-1", endpoint_url=f"{scheme}://{endpoint}")

    raise StorageConfigError(f"Unknown STORAGE_PROVIDER '{provider}'. Use azure, s3, r2 or minio.")
