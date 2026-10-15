"""Installer-generated UI identity; never touch ChatGPT profiles/cookies."""
from pathlib import Path
import uuid
import shutil

ROOT = Path(__file__).resolve().parents[2]
MARKER = '.ui-install-id'
UI_PROFILE = '.ui-browser'


def clear_ui_cache(root: Path = ROOT) -> list[str]:
    profile = root / UI_PROFILE
    if profile.is_symlink() or profile.is_junction():
        return []
    removed = []
    for name in ('Cache', 'Code Cache', 'GPUCache'):
        target = profile / 'Default' / name
        if not target.exists() or not target.resolve().is_relative_to(profile.resolve()):
            continue
        try:
            shutil.rmtree(target)
            removed.append(name)
        except OSError:
            # A still-open UI may hold cache files. The new install ID also invalidates every asset URL.
            continue
    return removed


def install_id(root: Path = ROOT) -> str:
    try:
        value = (root / MARKER).read_text(encoding='ascii').strip()
    except (OSError, UnicodeError):
        return 'dev'
    return value if len(value) == 32 and all(c in '0123456789abcdef' for c in value) else 'dev'


def mark_installed(root: Path = ROOT) -> str:
    value = uuid.uuid4().hex
    temporary = root / (MARKER + '.tmp')
    temporary.write_text(value, encoding='ascii')
    temporary.replace(root / MARKER)
    return value


if __name__ == '__main__':
    clear_ui_cache()
    mark_installed()
