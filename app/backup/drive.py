"""Google Drive storage adapter (slice 2).

Uploads encrypted artifacts to a Drive folder via a refresh-token OAuth flow
(drive.file scope). Lazy-imported by storage.get_storage() so slice 1 never
pulls the google libs. Only ciphertext ever reaches Drive — service.run_backup
encrypts BEFORE calling put(). Drive returns md5 checksums (not sha256), so
StoredMeta.checksum_algo is 'md5' and the caller compares like-for-like.
"""
import json

from app.backup.storage import StoredMeta, StoredObject

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _build_service(config):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    import google_auth_httplib2
    import httplib2

    with open(config["BACKUP_GDRIVE_CREDS"]) as fh:
        info = json.load(fh)["installed"]
    with open(config["BACKUP_GDRIVE_TOKEN"]) as fh:
        token = json.load(fh)
    creds = Credentials(
        token=None,
        refresh_token=token["refresh_token"],
        client_id=info["client_id"],
        client_secret=info["client_secret"],
        token_uri=info["token_uri"],
        scopes=SCOPES,
    )
    timeout = int(config.get("BACKUP_GDRIVE_TIMEOUT", 60))
    authed = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=timeout))
    return build("drive", "v3", http=authed, cache_discovery=False)


class GoogleDriveStorage:
    def __init__(self, config):
        self.config = config
        self.folder_name = config.get("BACKUP_GDRIVE_FOLDER_NAME", "RIC-CAS-Backups")
        self._svc = None
        self._folder_id = None

    @property
    def svc(self):
        if self._svc is None:
            self._svc = _build_service(self.config)
        return self._svc

    @property
    def folder_id(self):
        # drive.file only sees app-created files, so a manually-made folder is
        # invisible — the app must create (and then reuse) its own folder.
        if self._folder_id is None:
            q = (f"name='{self.folder_name}' and mimeType='application/vnd.google-apps.folder' "
                 "and trashed=false")
            res = self.svc.files().list(q=q, fields="files(id)", spaces="drive").execute()
            files = res.get("files", [])
            if files:
                self._folder_id = files[0]["id"]
            else:
                created = self.svc.files().create(
                    body={"name": self.folder_name, "mimeType": "application/vnd.google-apps.folder"},
                    fields="id").execute()
                self._folder_id = created["id"]
        return self._folder_id

    def put(self, local_path: str, remote_name: str) -> str:
        from googleapiclient.http import MediaFileUpload
        media = MediaFileUpload(local_path, resumable=False)
        created = self.svc.files().create(
            body={"name": remote_name, "parents": [self.folder_id]},
            media_body=media, fields="id",
            supportsAllDrives=True,
        ).execute()
        return created["id"]

    def stat(self, ref: str) -> StoredMeta:
        f = self.svc.files().get(fileId=ref, fields="size,md5Checksum",
                                 supportsAllDrives=True).execute()
        return StoredMeta(size=int(f["size"]), checksum=f["md5Checksum"], checksum_algo="md5")

    def get(self, ref: str, dest_path: str) -> None:
        from googleapiclient.http import MediaIoBaseDownload
        req = self.svc.files().get_media(fileId=ref)
        with open(dest_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, req)
            done = False
            while not done:
                _, done = downloader.next_chunk()

    def list(self) -> list:
        res = self.svc.files().list(
            q=f"'{self.folder_id}' in parents and trashed=false",
            fields="files(id,name,size)", pageSize=1000,
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        return [StoredObject(name=f["name"], ref=f["id"], size=int(f.get("size", 0)))
                for f in res.get("files", [])]

    def delete(self, ref: str) -> None:
        self.svc.files().delete(fileId=ref, supportsAllDrives=True).execute()
