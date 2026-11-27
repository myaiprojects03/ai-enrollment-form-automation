"""Data housekeeping.

    python -m scripts.maintain rotate     # re-encrypt everything under the first key in ENCRYPTION_KEYS
    python -m scripts.maintain purge      # erase personal data of finished enrollments after RETENTION_DAYS

Key rotation: put a new key first in ENCRYPTION_KEYS (keep the old ones after it), run rotate until it reports
zeros, then remove the old keys.
"""
from __future__ import annotations

import asyncio
import sys

from app.config import get_settings
from app.db.migrations import connect
from app.maintenance import purge, rotate
from app.security.crypto import FieldCipher


async def main(action: str) -> None:
    settings = get_settings()
    cipher = FieldCipher.from_setting(settings.encryption_keys)
    pool = await connect(settings.database_url)
    try:
        if action == "rotate":
            print("re-encrypted:", await rotate(pool, cipher))
        elif action == "purge":
            ids = await purge(pool, cipher, settings.retention_days)
            print(f"erased personal data of {len(ids)} enrollment(s) older than {settings.retention_days} days")
        else:
            sys.exit(__doc__)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else ""))
