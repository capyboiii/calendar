"""Đóng gói CalForge Studio để gửi người khác.

    python tools/package.py   -> dist/CalForge_Setup.exe          (người dùng chỉ cần bấm đúp file này)
                                 dist/CalForge_Studio_<ngày>.zip   (bản ZIP, cho người biết kỹ thuật)

CalForge_Setup.exe dựng bằng IExpress (có sẵn trong Windows): chứa ZIP + tools/setup.cmd; khi chạy, chép tool vào
%LOCALAPPDATA%/CalForge Studio (không cần admin, giữ dữ liệu cũ nếu cài đè) rồi chạy tools/cai_dat.ps1.

Chỉ gồm code + dữ liệu cần để chạy. KHÔNG gồm dữ liệu riêng của máy này: lịch đã làm (projects/), tài khoản
ChatGPT (.chrome-profiles/), khoá R2/Printify (calforge.json), email tài khoản, môi trường .venv, file tải về
được (font lấy từ repo, KJV + mô hình do CAI_DAT.bat tải lại).
"""
from __future__ import annotations

import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# chặn cứng các thư mục/file riêng tư dù .gitignore có sót
NEVER = ("projects/", ".chrome-profiles/", ".venv/", "dist/", ".cache/", ".git/", ".claude/", ".idea/", "models/",
         "__pycache__/")
NEVER_FILES = ("calforge.json", "data/account_emails.json", "data/kjv.json")


def files() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        out = [str(p.relative_to(ROOT)).replace("\\", "/") for p in ROOT.rglob("*") if p.is_file()]
    keep = []
    for f in out:
        f = f.replace("\\", "/")
        if any(f.startswith(n) or f"/{n}" in f for n in NEVER) or f in NEVER_FILES or f.endswith(".pyc"):
            continue
        if (ROOT / f).is_file():
            keep.append(f)
    return sorted(keep)


def build_exe(app_zip: Path) -> Path | None:
    """Gói ZIP + setup.cmd thành 1 file .exe tự giải nén bằng IExpress của Windows."""
    import os
    import shutil

    iexpress = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "iexpress.exe"
    if not iexpress.exists():
        print("Không có iexpress.exe - chỉ tạo bản ZIP")
        return None
    build = ROOT / "dist" / "_build"
    shutil.rmtree(build, ignore_errors=True)
    build.mkdir(parents=True)
    shutil.copy(app_zip, build / "app.zip")
    cmd = (ROOT / "tools" / "setup.cmd").read_text(encoding="utf-8")
    crlf = "".join(line + chr(13) + chr(10) for line in cmd.splitlines())   # cmd.exe cần CRLF (nhãn/goto)
    (build / "setup.cmd").write_bytes(crlf.encode("ascii"))
    target = ROOT / "dist" / "CalForge_Setup.exe"
    target.unlink(missing_ok=True)
    src_dir = str(build) + chr(92)                          # IExpress cần dấu \ cuối đường dẫn
    sed = f"""[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=1
HideExtractAnimation=1
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=%InstallPrompt%
DisplayLicense=%DisplayLicense%
FinishMessage=%FinishMessage%
TargetName=%TargetName%
FriendlyName=%FriendlyName%
AppLaunched=%AppLaunched%
PostInstallCmd=%PostInstallCmd%
AdminQuietInstCmd=%AdminQuietInstCmd%
UserQuietInstCmd=%UserQuietInstCmd%
SourceFiles=SourceFiles
[Strings]
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName={target}
FriendlyName=CalForge Studio
AppLaunched=cmd /c setup.cmd
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
FILE0="setup.cmd"
FILE1="app.zip"
[SourceFiles]
SourceFiles0={src_dir}
[SourceFiles0]
%FILE0%=
%FILE1%=
"""
    sed_file = build / "setup.sed"
    sed_file.write_text(sed, encoding="ascii")
    subprocess.run([str(iexpress), "/N", "/Q", str(sed_file)], check=False)
    shutil.rmtree(build, ignore_errors=True)
    if not target.exists():
        print("IExpress không tạo được file .exe")
        return None
    print(f"Bộ cài 1 file -> {target} ({target.stat().st_size / 1e6:.1f} MB)")
    return target


def main() -> Path:
    out = ROOT / "dist" / f"CalForge_Studio_{time.strftime('%Y%m%d')}.zip"
    out.parent.mkdir(exist_ok=True)
    names = files()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in names:
            z.write(ROOT / f, f"CalForge_Studio/{f}")
    print(f"{len(names)} file -> {out} ({out.stat().st_size / 1e6:.1f} MB)")
    build_exe(out)
    return out


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
