"""Đóng gói CalForge Studio thành bộ cài app cho Windows.

    python tools/package.py   ->  dist/CalForge_Studio_Setup.exe

Người dùng chỉ cần: bấm đúp Setup.exe -> Next -> Install -> app tự mở. Không cài Python, không cửa sổ đen
(máy có card NVIDIA thì cần mạng để tải thêm bộ làm nét ảnh Real-ESRGAN ~2.5 GB lúc cài, xem calforge/gpu_setup.py): bộ cài chứa sẵn Python (bản nhúng), mọi thư viện, font và Kinh Thánh KJV. Cần sẵn Google Chrome
(app tự nhắc tải nếu máy chưa có). Cài vào %LOCALAPPDATA%\\CalForge Studio (không cần quyền admin); cài bản mới
đè lên giữ nguyên lịch đã làm, tài khoản, khoá R2.

Máy đóng gói cần: Python 3.12 (cùng bản với Python nhúng), mạng lần đầu (tải Python nhúng), Inno Setup 6
(winget install JRSoftware.InnoSetup).

KHÔNG gồm dữ liệu riêng của máy này: lịch đã làm (projects/), tài khoản ChatGPT (.chrome-profiles/), khoá
R2/Printify (calforge.json), email tài khoản, log.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
CACHE = DIST / "_cache"
PY_VER = "3.12.10"
PY_EMBED = f"https://www.python.org/ftp/python/{PY_VER}/python-{PY_VER}-embed-amd64.zip"
# chặn cứng các thư mục/file riêng tư dù .gitignore có sót
NEVER = ("projects/", ".chrome-profiles/", ".venv/", "dist/", ".cache/", ".git/", ".claude/", ".idea/", "models/",
         "__pycache__/", "logs/")
NEVER_FILES = ("calforge.json", "data/account_emails.json")
EXTRA = ("data/kjv.json",)          # không nằm trong git (tải về) nhưng app cần, phạm vi công cộng


def files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout.splitlines()
    keep = []
    for f in [*out, *EXTRA]:
        f = f.replace("\\", "/")
        if any(f.startswith(n) or f"/{n}" in f for n in NEVER) or f in NEVER_FILES or f.endswith(".pyc"):
            continue
        if (ROOT / f).is_file():
            keep.append(f)
    return sorted(set(keep))


def _python(app: Path) -> None:
    """Python nhúng + thư viện cài sẵn vào app/python."""
    if sys.version_info[:2] != (3, 12):
        sys.exit("Cần chạy bằng Python 3.12 (khớp Python nhúng) để cài đúng thư viện.")
    CACHE.mkdir(parents=True, exist_ok=True)
    embed = CACHE / Path(PY_EMBED).name
    if not embed.exists():
        print(f"Tải Python nhúng {PY_VER}...")
        urllib.request.urlretrieve(PY_EMBED, embed)
    pydir = app / "python"
    with zipfile.ZipFile(embed) as z:
        z.extractall(pydir)
    # thư mục app (..) để chạy được "-m calforge", site-packages cho thư viện
    # ..\gpu: torch + spandrel cho card NVIDIA, tải lúc cài (calforge/gpu_setup.py); nằm ngoài python\ nên cài đè không mất
    (pydir / "python312._pth").write_text("python312.zip\n.\nLib\\site-packages\n..\\gpu\n..\nimport site\n",
                                         encoding="ascii")
    print("Cài thư viện vào Python nhúng...")
    subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location",
                    "--only-binary=:all:", "--target", str(pydir / "Lib" / "site-packages"),
                    "-r", str(ROOT / "requirements.txt"), "pip"], check=True)   # pip: để gpu_setup tải torch
    for cache in pydir.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def _icon(app: Path) -> None:
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((16, 28, 240, 240), 36, fill=(47, 93, 80))
    d.rectangle((16, 84, 240, 100), fill=(255, 255, 255))
    for x in (76, 180):
        d.rounded_rectangle((x - 9, 8, x + 9, 60), 8, fill=(34, 32, 28))
    for i in range(3):
        for j in range(4):
            x0, y0 = 44 + j * 45, 118 + i * 38
            d.rounded_rectangle((x0, y0, x0 + 30, y0 + 24), 5, fill=(227, 238, 233))
    im.save(app / "calforge.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


ISS = r"""
[Setup]
AppId={{6B0E6C3A-4F1D-4B8E-9C2E-CA1F0E5D2A71}
AppName=CalForge Studio
AppVersion=%(version)s
AppPublisher=CalForge
DefaultDirName={localappdata}\CalForge Studio
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=%(out)s
OutputBaseFilename=CalForge_Studio_Setup
SetupIconFile=%(app)s\calforge.ico
UninstallDisplayIcon={app}\calforge.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[InstallDelete]
; thư viện cũ bỏ đi trước khi chép bản mới (dữ liệu người dùng không nằm ở đây)
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\calforge"

[Files]
Source: "%(app)s\*"; DestDir: "{app}"; Excludes: "\calforge.json"; Flags: ignoreversion recursesubdirs createallsubdirs
; khoá R2 kèm sẵn (chỉ khi đóng gói bằng --with-r2): chỉ chép nếu máy chưa có calforge.json, không đè khoá người dùng
Source: "%(app)s\calforge.json"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall skipifsourcedoesntexist

[Icons]
Name: "{userdesktop}\CalForge Studio"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m calforge.app"; WorkingDir: "{app}"; IconFilename: "{app}\calforge.ico"
Name: "{userprograms}\CalForge Studio"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m calforge.app"; WorkingDir: "{app}"; IconFilename: "{app}\calforge.ico"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\gpu"
Type: filesandordirs; Name: "{app}\models"

[Run]
; máy có card NVIDIA: tải bộ làm nét ảnh Real-ESRGAN (~2.5 GB, chỉ lần đầu); máy khác thoát ngay
Filename: "{app}\python\python.exe"; Parameters: "-m calforge.gpu_setup"; WorkingDir: "{app}"; StatusMsg: "Checking NVIDIA graphics card (image sharpening)..."; Flags: waituntilterminated skipifsilent
Filename: "{app}\python\pythonw.exe"; Parameters: "-m calforge.app"; WorkingDir: "{app}"; Description: "Open CalForge Studio"; Flags: postinstall nowait skipifsilent
"""


def _iscc() -> Path:
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles(x86)", ""),
                 os.environ.get("ProgramFiles", "")):
        p = Path(base) / "Programs" / "Inno Setup 6" / "ISCC.exe"
        if p.exists():
            return p
        p = Path(base) / "Inno Setup 6" / "ISCC.exe"
        if p.exists():
            return p
    sys.exit("Chưa có Inno Setup 6: winget install JRSoftware.InnoSetup")


def _bundle_r2(app: Path) -> None:
    """python tools/package.py --with-r2: kèm KHOÁ R2 của máy này (chỉ mục "r2" trong calforge.json, không gì khác)
    để người nhận đẩy R2 + xuất CSV được ngay. Ai có bộ cài đều đọc được khoá này - chỉ gửi người tin cậy, nên dùng
    API token R2 giới hạn đúng 1 bucket."""
    import json
    try:
        r2 = json.loads((ROOT / "calforge.json").read_text(encoding="utf-8")).get("r2") or {}
    except (OSError, ValueError):
        r2 = {}
    need = ("account_id", "access_key_id", "secret_access_key", "bucket", "public_url")
    missing = [k for k in need if not r2.get(k)]
    if missing:
        sys.exit(f"--with-r2: calforge.json chưa có đủ khoá R2 ({', '.join(missing)})")
    (app / "calforge.json").write_text(json.dumps({"r2": r2}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Kèm khoá R2 (bucket {r2['bucket']}) - bộ cài này chứa khoá bí mật, chỉ gửi người tin cậy")


def _guide_pdf() -> None:
    """dist/Huong_dan_CalForge_Studio.pdf từ HUONG_DAN.html (gửi kèm bộ cài), in bằng Chrome."""
    sys.path.insert(0, str(ROOT))
    from calforge.app import _chrome
    chrome = _chrome()
    if not chrome:
        print("Không có Chrome - bỏ qua PDF hướng dẫn")
        return
    out = DIST / "Huong_dan_CalForge_Studio.pdf"
    subprocess.run([str(chrome), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={out}", (ROOT / "HUONG_DAN.html").as_uri()], capture_output=True, check=False)
    print(f"Hướng dẫn -> {out}" if out.exists() else "Không in được PDF hướng dẫn")


def main() -> Path:
    import time

    iscc = _iscc()
    app = DIST / "app"
    shutil.rmtree(app, ignore_errors=True)
    names = files()
    for f in names:
        (app / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, app / f)
    print(f"{len(names)} file của tool")
    _python(app)
    _icon(app)
    if "--with-r2" in sys.argv:
        _bundle_r2(app)
    iss = DIST / "setup.iss"
    iss.write_text(ISS % {"version": time.strftime("%Y.%m.%d"), "out": DIST, "app": app}, encoding="utf-8-sig")
    subprocess.run([str(iscc), "/Q", str(iss)], check=True)
    shutil.rmtree(app, ignore_errors=True)
    iss.unlink()
    target = DIST / "CalForge_Studio_Setup.exe"
    print(f"Bộ cài -> {target} ({target.stat().st_size / 1e6:.0f} MB)")
    _guide_pdf()
    return target


if __name__ == "__main__":
    main()
