"""Named workspaces for UI runs; Chrome accounts and the clone queue stay shared."""
from pathlib import Path
import json
import re
import threading
import uuid
from datetime import datetime

DIRECTORY = '_du_an'
_LOCK = threading.RLock()


def entries(root: Path) -> list[dict]:
    result = []
    for file in sorted((Path(root) / DIRECTORY).glob('*/project.json')):
        try:
            item = json.loads(file.read_text(encoding='utf-8'))
            if (re.fullmatch(r'[a-f0-9]{32}', file.parent.name) and item.get('id') == file.parent.name
                    and isinstance(item.get('name'), str) and item['name'].strip()):
                result.append(item)
        except (OSError, ValueError, AttributeError):
            continue
    return result


def require(root: Path, project_id: str) -> Path:
    if not isinstance(project_id, str) or not re.fullmatch(r'[a-f0-9]{32}', project_id):
        raise ValueError('Tạo hoặc chọn dự án trước khi bắt đầu.')
    target = Path(root) / DIRECTORY / project_id
    if not target.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('Đường dẫn dự án không hợp lệ.')
    item = next((p for p in entries(root) if p['id'] == project_id), None)
    if item is None:
        raise ValueError('Dự án không còn tồn tại. Hãy chọn lại dự án.')
    if item.get('storage_path'):
        target = Path(item['storage_path'])
        if not target.is_absolute():
            raise ValueError('Đường dẫn lưu dự án không hợp lệ.')
        if not target.is_dir():
            raise ValueError('Không truy cập được thư mục dự án. Kiểm tra ổ đĩa lưu dự án.')
    return target


def create(root: Path, name: str, storage_parent: str = '') -> dict:
    if not isinstance(storage_parent, str):
        raise ValueError('Đường dẫn thư mục lưu không hợp lệ.')
    storage_parent = storage_parent.strip()
    name = str(name).strip()
    if not name or len(name) > 100 or any(ord(c) < 32 for c in name):
        raise ValueError('Tên dự án cần từ 1 đến 100 ký tự.')
    with _LOCK:
        if any(p['name'].casefold() == name.casefold() for p in entries(root)):
            raise ValueError('Tên dự án đã có. Chọn dự án đó hoặc đặt tên khác.')
        item = {'id': uuid.uuid4().hex, 'name': name, 'created': datetime.now().isoformat(timespec='seconds')}
        target = Path(root) / DIRECTORY / item['id']
        if not target.resolve().is_relative_to(Path(root).resolve()):
            raise ValueError('Đường dẫn dự án không hợp lệ.')
        target.mkdir(parents=True)
        if storage_parent:
            parent = Path(storage_parent).expanduser()
            if not parent.is_absolute() or not parent.is_dir():
                target.rmdir()
                raise ValueError('Chọn thư mục lưu có sẵn trên máy (đường dẫn đầy đủ).')
            # Dedicated child: deleting a project must never delete the selected parent.
            safe_name = re.sub(r'[^\w-]+', '-', name, flags=re.UNICODE).strip('-_')[:32] or 'CalForge'
            destination = parent / (safe_name + '-' + item['id'][:8])
            try:
                destination.mkdir()
                probe = destination / '.write-test'
                probe.write_text('ok', encoding='utf-8')
                probe.unlink()
            except OSError:
                if destination.is_dir() and not any(destination.iterdir()):
                    destination.rmdir()
                target.rmdir()
                raise
            item['storage_path'] = str(destination.resolve())
        temporary = target / 'project.tmp'
        temporary.write_text(json.dumps(item, ensure_ascii=False), encoding='utf-8')
        temporary.replace(target / 'project.json')
        return item


def run_root(root: Path, params: dict) -> Path:
    return require(root, params['project_id']) if params.get('project_id') else Path(root)


def roots(root: Path) -> list[Path]:
    """Registered storage roots, including temporarily unavailable drives."""
    return [Path(root)] + [Path(p['storage_path']) for p in entries(root) if p.get('storage_path')]


def contains(root: Path, target: Path) -> bool:
    return any(Path(target).resolve().is_relative_to(p.resolve()) for p in roots(root))
