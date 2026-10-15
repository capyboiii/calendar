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
    if not any(p['id'] == project_id for p in entries(root)):
        raise ValueError('Dự án không còn tồn tại. Hãy chọn lại dự án.')
    return target


def create(root: Path, name: str) -> dict:
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
        temporary = target / 'project.tmp'
        temporary.write_text(json.dumps(item, ensure_ascii=False), encoding='utf-8')
        temporary.replace(target / 'project.json')
        return item


def run_root(root: Path, params: dict) -> Path:
    return require(root, params['project_id']) if params.get('project_id') else Path(root)
