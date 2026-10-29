# OtoClean.exe derleme betiği: testleri çalıştırır, sonra PyInstaller ile paketler.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = ".\.venv\Scripts\python.exe"

& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Testler başarısız, derleme durduruldu." }

# Kullanılmayan ağır Qt modülleri dışarıda bırakılır (boyut ~%70 küçülür)
$exclude = @(
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtQuick",
    "PySide6.QtQml", "PySide6.QtQuick3D", "PySide6.Qt3DCore", "PySide6.QtMultimedia",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtNetwork", "PySide6.QtSql",
    "PySide6.QtOpenGL", "PySide6.QtSvg", "tkinter", "unittest", "pytest"
) | ForEach-Object { "--exclude-module=$_" }

& $py -m PyInstaller --noconfirm --clean --windowed --name OtoClean @exclude run_otoclean.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller başarısız." }
Write-Host "Hazır: dist\OtoClean\OtoClean.exe"
