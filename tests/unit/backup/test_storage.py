"""Task 2 — BackupStorage protocol + LocalStorage adapter."""
import hashlib

from app.backup.storage import LocalStorage, get_storage


def test_put_get_stat_roundtrip(tmp_path):
    src = tmp_path / "a.bin"
    src.write_bytes(b"hello ledger")
    store = LocalStorage(str(tmp_path / "store"))
    ref = store.put(str(src), "db-2026-07-05.enc")
    meta = store.stat(ref)
    assert meta.size == 12
    assert meta.checksum == hashlib.sha256(b"hello ledger").hexdigest()
    assert meta.checksum_algo == "sha256"
    dest = tmp_path / "out.bin"
    store.get(ref, str(dest))
    assert dest.read_bytes() == b"hello ledger"


def test_list_and_delete(tmp_path):
    store = LocalStorage(str(tmp_path / "store"))
    src = tmp_path / "a"
    src.write_bytes(b"x")
    ref = store.put(str(src), "one.enc")
    assert any(o.name == "one.enc" for o in store.list())
    store.delete(ref)
    assert store.list() == []


def test_factory_local(tmp_path):
    st = get_storage({"BACKUP_STORAGE": "local", "BACKUP_LOCAL_DIR": str(tmp_path)})
    assert isinstance(st, LocalStorage)


def test_factory_unknown_raises():
    import pytest
    with pytest.raises(ValueError):
        get_storage({"BACKUP_STORAGE": "s3"})
