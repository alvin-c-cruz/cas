"""Storage adapters for backup artifacts.

LocalStorage = on-server (slice 1). GoogleDriveStorage (slice 2) lives in
drive.py and is imported lazily by the factory, so importing this module never
pulls the Google client stack.
"""
import hashlib
import os
import shutil
from dataclasses import dataclass
from typing import Protocol


@dataclass
class StoredMeta:
    size: int
    checksum: str
    checksum_algo: str


@dataclass
class StoredObject:
    name: str
    ref: str
    size: int


class BackupStorage(Protocol):
    def put(self, local_path: str, remote_name: str) -> str: ...
    def stat(self, ref: str) -> StoredMeta: ...
    def get(self, ref: str, dest_path: str) -> None: ...
    def list(self) -> list: ...
    def delete(self, ref: str) -> None: ...


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class LocalStorage:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

    def _path(self, ref: str) -> str:
        return os.path.join(self.base_dir, ref)

    def put(self, local_path: str, remote_name: str) -> str:
        shutil.copy2(local_path, self._path(remote_name))
        return remote_name

    def stat(self, ref: str) -> StoredMeta:
        p = self._path(ref)
        return StoredMeta(size=os.path.getsize(p), checksum=_sha256_file(p),
                          checksum_algo="sha256")

    def get(self, ref: str, dest_path: str) -> None:
        shutil.copy2(self._path(ref), dest_path)

    def list(self) -> list:
        out = []
        for name in sorted(os.listdir(self.base_dir)):
            p = self._path(name)
            if os.path.isfile(p):
                out.append(StoredObject(name=name, ref=name, size=os.path.getsize(p)))
        return out

    def delete(self, ref: str) -> None:
        os.remove(self._path(ref))


def get_storage(config) -> BackupStorage:
    kind = config.get("BACKUP_STORAGE", "local")
    if kind == "local":
        return LocalStorage(config["BACKUP_LOCAL_DIR"])
    if kind == "gdrive":
        from app.backup.drive import GoogleDriveStorage  # lazy: no google import for slice 1
        return GoogleDriveStorage(config)
    raise ValueError(f"unknown BACKUP_STORAGE={kind!r}")
