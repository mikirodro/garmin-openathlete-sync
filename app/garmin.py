from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, is_zipfile

from garminconnect import Garmin

MAX_FIT_BYTES = 20 * 1024 * 1024


class GarminClient:
    def __init__(self, email, password, token_dir: Path, interactive=False):
        token_dir.mkdir(parents=True, exist_ok=True)
        self.email, self.password = email, password
        self.token_dir = str(token_dir)
        self.interactive = interactive
        self.client = None

    def login(self):
        def mfa():
            if not self.interactive:
                raise RuntimeError("Garmin requires MFA; run python -m app --login interactively")
            return input("Garmin MFA code: ").strip()
        # Recreate with credentials: recent Garmin versions clear the password after login.
        self.client = Garmin(self.email, self.password, prompt_mfa=mfa)
        result = self.client.login(self.token_dir)
        if result and result[0]:
            raise RuntimeError("Garmin login incomplete; run python -m app --login")

    def recent(self, limit):
        """Page size, not a cap on the total number of activities."""
        start = 0
        seen = set()
        while True:
            page = self.client.get_activities(start, limit)
            if isinstance(page, dict):
                page = page.get("activityList", [])
            if not page:
                return
            ids = {str(a.get("activityId")) for a in page}
            if ids <= seen:
                raise RuntimeError("Garmin returned a repeated page")
            seen.update(ids)
            yield from page
            start += len(page)

    def download_fit(self, activity_id, out: Path):
        raw = self.client.download_activity(
            activity_id, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL,
        )
        if is_zipfile(BytesIO(raw)):
            with ZipFile(BytesIO(raw)) as archive:
                fits = [entry for entry in archive.infolist()
                        if not entry.is_dir() and entry.filename.lower().endswith(".fit")]
                if len(fits) != 1:
                    raise ValueError("Expected exactly one FIT activity in Garmin ZIP")
                if fits[0].file_size > MAX_FIT_BYTES:
                    raise ValueError("FIT exceeds OpenAthlete's 20 MB limit")
                # Read bytes only; never extract archive-controlled paths.
                raw = archive.read(fits[0])
        if len(raw) < 12 or len(raw) > MAX_FIT_BYTES or raw[8:12] != b".FIT":
            raise ValueError("Invalid FIT file or file exceeds 20 MB")
        temporary = out.with_suffix(".fit.part")
        temporary.write_bytes(raw)
        temporary.replace(out)
