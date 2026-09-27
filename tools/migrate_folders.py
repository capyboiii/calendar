"""Chuyển projects/ cũ sang cách đặt tên mới (chạy một lần, chạy lại cũng không sao).

    projects/<chủ đề>/r1a2-plants-of-scripture/   ->  projects/<chủ đề>/Plants of Scripture/
    projects/<chủ đề>/angles.json, ideation/, _batch.json  ->  projects/<chủ đề>/_he_thong/
    projects/<chủ đề>/_bao_cao_batch.md            ->  projects/<chủ đề>/Báo cáo batch.md

    python tools/migrate_folders.py [projects]
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calforge import layout  # noqa: E402

OLD_BOOK = re.compile(r"^(r\d+a\d+)-")


def migrate_keyword(kdir: Path) -> list[str]:
    done = []
    layout.ensure_system(kdir)
    for old, new in (("angles.json", layout.angles_file(kdir)), ("ideation", layout.ideation_dir(kdir)),
                     ("_batch.json", layout.batch_file(kdir)), ("_bao_cao_batch.md", layout.batch_report_file(kdir))):
        src = kdir / old
        if src.exists() and not new.exists():
            shutil.move(str(src), str(new))
            done.append(f"{kdir.name}/{old} -> {new.relative_to(kdir)}")

    renamed = {}
    for d in sorted(kdir.iterdir()):
        m = OLD_BOOK.match(d.name)
        if not d.is_dir() or not m or not (d / layout.SYSTEM).is_dir():
            continue
        aid = m.group(1)
        (d / layout.SYSTEM / layout.ANGLE_ID).write_text(aid, encoding="utf-8")
        try:
            title = json.loads(layout.concept_file(d).read_text(encoding="utf-8")).get("title")
        except (OSError, ValueError):
            title = None
        base = layout.book_folder_name(title or d.name[len(aid) + 1:].replace("-", " ").title())
        new, i = kdir / base, 2
        while new.exists():
            new, i = kdir / f"{base} ({i})", i + 1
        d.rename(new)
        renamed[d.name] = new.name
        done.append(f"{kdir.name}/{d.name} -> {new.name}")

    bf = layout.batch_file(kdir)
    if renamed and bf.exists():
        batch = json.loads(bf.read_text(encoding="utf-8"))
        batch["concepts"] = [renamed.get(c, c) for c in batch.get("concepts", [])]
        for row in batch.get("report", []):
            row["concept"] = renamed.get(row.get("concept"), row.get("concept"))
        bf.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
    return done


def main(root: Path) -> None:
    for kdir in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        for line in migrate_keyword(kdir):
            print(line)


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "projects"))
