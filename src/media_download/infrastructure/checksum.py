"""Checksum adapters for media download artifacts."""

from __future__ import annotations

from pathlib import Path


class Sha256ChecksumCalculator:
    """Calculate SHA256 checksums without loading full media files into memory."""

    def sha256(self, path: str) -> str:
        import hashlib

        digest = hashlib.sha256()
        with Path(path).open("rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
