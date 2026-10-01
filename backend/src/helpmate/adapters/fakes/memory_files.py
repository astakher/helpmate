"""In-memory file store (HELPMATE_FILES=memory): uploaded bytes live as long as the process."""

from __future__ import annotations


class InMemoryFileStore:
    name = "memory"
    is_fake = True

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    async def get(self, key: str) -> bytes | None:
        found = self.objects.get(key)
        return found[0] if found else None

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)
