# Stand-in for Workstream B - not part of the Part C deliverable
"""S3 file store (HELPMATE_FILES=s3): SeaweedFS from infra/docker-compose.yml on 127.0.0.1:8333.

Uses the MinIO client (S3 SigV4) in a thread. The bucket is created on first use. Credentials
are S3_ACCESS_KEY / S3_SECRET_KEY from .env, the same ones the container starts with; it refuses
wrong and anonymous requests (checked Oct 1).
"""

from __future__ import annotations

import asyncio
import io
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error


class S3FileStore:
    name = "s3"
    is_fake = False

    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str) -> None:
        url = urlparse(endpoint)
        self._client = Minio(
            url.netloc or url.path,
            access_key=access_key,
            secret_key=secret_key,
            secure=url.scheme == "https",
        )
        self._bucket = bucket
        self._ready = False
        self._lock = asyncio.Lock()

    async def _bucket_ready(self) -> None:
        async with self._lock:
            if not self._ready:
                if not await asyncio.to_thread(self._client.bucket_exists, self._bucket):
                    await asyncio.to_thread(self._client.make_bucket, self._bucket)
                self._ready = True

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await self._bucket_ready()
        await asyncio.to_thread(
            self._client.put_object,
            self._bucket,
            key,
            io.BytesIO(data),
            len(data),
            content_type=content_type,
        )

    async def get(self, key: str) -> bytes | None:
        await self._bucket_ready()

        def read() -> bytes | None:
            try:
                response = self._client.get_object(self._bucket, key)
            except S3Error as exc:
                if exc.code in ("NoSuchKey", "NoSuchObject"):
                    return None
                raise
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        return await asyncio.to_thread(read)

    async def delete(self, key: str) -> None:
        await self._bucket_ready()
        await asyncio.to_thread(self._client.remove_object, self._bucket, key)
