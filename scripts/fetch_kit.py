import sys
import zipfile

import httpx

from core.config import auth_headers, load_settings


def main() -> int:
    settings = load_settings()
    settings.kit_dir.mkdir(parents=True, exist_ok=True)
    target = settings.kit_dir / "start-kit.zip"
    response = httpx.get(settings.kit_url, headers=auth_headers(settings), timeout=60)
    if response.status_code != 200:
        print(f"status {response.status_code}")
        print(response.text[:2000])
        return 1
    target.write_bytes(response.content)
    with zipfile.ZipFile(target) as archive:
        for member in archive.namelist():
            resolved = (settings.kit_dir / member).resolve()
            if not resolved.is_relative_to(settings.kit_dir.resolve()):
                print(f"refusing unsafe path {member}")
                return 1
        archive.extractall(settings.kit_dir)
        for info in archive.infolist():
            print(f"{info.file_size:>10}  {info.filename}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
