# Cài CalForge Studio cho máy Windows mới - chạy bằng CAI_DAT.bat (bấm đúp).
# Tự cài Python 3.12 và Google Chrome nếu thiếu (qua winget), tạo môi trường riêng .venv, cài thư viện,
# tải font / Kinh Thánh KJV / mô hình làm nét ảnh, tạo biểu tượng "CalForge Studio" ngoài màn hình.
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Step($n, $msg) { Write-Host ""; Write-Host "[$n/6] $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "   ✔ $msg" -ForegroundColor Green }
function Fail($msg) {
    Write-Host ""; Write-Host "   ✘ $msg" -ForegroundColor Red
    Write-Host "   Chụp màn hình này gửi người hỗ trợ." -ForegroundColor Yellow
    Read-Host "Bấm Enter để đóng"; exit 1
}
function HasWinget { return [bool](Get-Command winget -ErrorAction SilentlyContinue) }

# ---------------------------------------------------------------- 1. Python
Step 1 "Kiểm tra Python"
$py = $null
foreach ($cand in @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe", "C:\Program Files\Python312\python.exe")) {
    if (Test-Path $cand) { $py = $cand; break }
}
if (-not $py -and (Get-Command py -ErrorAction SilentlyContinue)) {
    try { $p = & py -3.12 -c "import sys; print(sys.executable)" 2>$null; if ($LASTEXITCODE -eq 0 -and $p) { $py = $p.Trim() } } catch {}
}
if (-not $py) {
    if (-not (HasWinget)) {
        Start-Process "https://www.python.org/downloads/release/python-31210/"
        Fail "Máy chưa có Python 3.12. Hãy tải và cài từ trang vừa mở (tích ô 'Add python.exe to PATH'), rồi chạy lại CAI_DAT.bat."
    }
    Write-Host "   Đang cài Python 3.12 (vài phút)..."
    winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Host
    $py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    if (-not (Test-Path $py)) { Fail "Cài Python không thành công." }
}
Ok "Python: $py"

# ---------------------------------------------------------------- 2. Chrome
Step 2 "Kiểm tra Google Chrome"
$chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
            "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
            "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) {
    if (-not (HasWinget)) {
        Start-Process "https://www.google.com/chrome/"
        Fail "Máy chưa có Google Chrome. Hãy cài từ trang vừa mở rồi chạy lại CAI_DAT.bat."
    }
    Write-Host "   Đang cài Google Chrome..."
    winget install -e --id Google.Chrome --silent --accept-package-agreements --accept-source-agreements | Out-Host
}
Ok "Chrome đã có"

# ---------------------------------------------------------------- 3. Môi trường riêng + thư viện
Step 3 "Cài thư viện (lần đầu mất 5-15 phút)"
if (-not (Test-Path ".venv\Scripts\python.exe")) { & $py -m venv .venv; if ($LASTEXITCODE) { Fail "Không tạo được môi trường .venv" } }
$vpy = Join-Path $Root ".venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip --quiet --disable-pip-version-check
& $vpy -m pip install -r requirements.txt --disable-pip-version-check
if ($LASTEXITCODE) { Fail "Cài thư viện lỗi (kiểm tra mạng rồi chạy lại)." }
Ok "Thư viện xong"

# ---------------------------------------------------------------- 4. Làm nét ảnh bằng card NVIDIA (nếu có)
Step 4 "Kiểm tra card đồ hoạ NVIDIA"
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    Write-Host "   Có card NVIDIA - cài bộ làm nét ảnh (~2.5 GB, lâu)..."
    & $vpy -m pip install torch --index-url https://download.pytorch.org/whl/cu121 --disable-pip-version-check
    & $vpy -m pip install spandrel --disable-pip-version-check
    if ($LASTEXITCODE) { Write-Host "   ! Không cài được, tool vẫn chạy nhưng ảnh làm nét kém hơn." -ForegroundColor Yellow }
    else { Ok "Làm nét ảnh bằng GPU" }
} else {
    Write-Host "   Không có card NVIDIA - tool vẫn chạy, ảnh làm nét bằng cách thường (kém hơn)." -ForegroundColor Yellow
}

# ---------------------------------------------------------------- 5. Font, Kinh Thánh, mô hình
Step 5 "Tải font, Kinh Thánh KJV, mô hình làm nét ảnh"
& $vpy tools\fetch_assets.py
if ($LASTEXITCODE) { Fail "Tải dữ liệu lỗi (kiểm tra mạng rồi chạy lại)." }
Ok "Dữ liệu xong"

# ---------------------------------------------------------------- 6. Biểu tượng ngoài màn hình
Step 6 "Tạo biểu tượng CalForge Studio ngoài màn hình"
$lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "CalForge Studio.lnk"
$sh = New-Object -ComObject WScript.Shell
$s = $sh.CreateShortcut($lnk)
$s.TargetPath = Join-Path $Root "start_ui.bat"
$s.WorkingDirectory = $Root
$s.IconLocation = "$env:SystemRoot\System32\shell32.dll,165"
$s.Save()
Ok "Đã tạo: $lnk"

Write-Host ""
Write-Host "==================== CÀI XONG ====================" -ForegroundColor Green
Write-Host " Tool đang mở trên trình duyệt."
Write-Host " Lần sau: bấm đúp biểu tượng 'CalForge Studio' ngoài màn hình."
Write-Host "=================================================="
Start-Process (Join-Path $Root "start_ui.bat") -WorkingDirectory $Root
Start-Sleep -Seconds 4
