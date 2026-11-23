import os

import boto3


class S3Storage:
    def __init__(self, bucket, access_key, secret_key, region):
        self.bucket = bucket
        self.client = boto3.client(
            "s3", aws_access_key_id=access_key,
            aws_secret_access_key=secret_key, region_name=region)

    def put_object(self, key, data):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)

    def upload_test_case(self, problem_id, number, input_text, output_text):
        base = f"test_cases/{problem_id}/{number:02d}"
        self.put_object(base, input_text.encode("utf-8"))
        self.put_object(base + ".a", output_text.encode("utf-8"))

    def upload_checker(self, problem_id, filename, data):
        self.put_object(f"test_cases/{problem_id}/{filename}", data)

    def empty_problem(self, problem_id):
        prefix = f"test_cases/{problem_id}/"
        pages = self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix)
        for page in pages:
            objects = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objects:
                self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": objects})


def get_storage():
    names = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_STORAGE_BUCKET_NAME", "AWS_S3_REGION_NAME"]
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        raise ValueError("Missing environment variables: " + ", ".join(missing))
    key, secret, bucket, region = (os.environ[n] for n in names)
    return S3Storage(bucket, key, secret, region)
