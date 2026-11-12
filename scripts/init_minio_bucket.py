"""Create the application MinIO bucket if it does not exist."""

from __future__ import annotations

import os
import sys
import time

from minio import Minio
from minio.error import S3Error


def main() -> int:
    endpoint = os.environ.get("MINIO_ENDPOINT", "minio:9000")
    access_key = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
    secret_key = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
    bucket = os.environ.get("MINIO_BUCKET", "rag-documents")
    secure = os.environ.get("MINIO_SECURE", "false").lower() in {"1", "true", "yes"}
    retries = int(os.environ.get("MINIO_INIT_RETRIES", "30"))

    client = Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
    )

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)
                print(f"Created bucket '{bucket}'")
            else:
                print(f"Bucket '{bucket}' already exists")
            return 0
        except (S3Error, OSError) as exc:
            last_error = exc
            print(f"Attempt {attempt}/{retries} failed: {exc}", file=sys.stderr)
            time.sleep(2)

    print(f"Failed to ensure bucket '{bucket}': {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
