# OCR отрендеренных страниц через Windows.Media.Ocr (русский + английский).
param(
    [string]$Root = "pdf_pages",
    [string]$Out = "pdf_text",
    [int]$Limit = 0
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime

$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage, ContentType = WindowsRuntime]

function Await($WinRtTask, $ResultType) {
    $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
            $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
        })[0]
    $netTask = $asTask.MakeGenericMethod($ResultType).Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}

$engine = $null
foreach ($code in @("ru-RU", "en-US")) {
    try {
        $lang = New-Object Windows.Globalization.Language $code
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
        if ($engine) { Write-Host "OCR язык: $code"; break }
    } catch { }
}
if (-not $engine) { throw "Не удалось создать OCR-движок" }

function Get-OcrText([string]$Path) {
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $lines = @()
    foreach ($line in $result.Lines) { $lines += $line.Text }
    $bitmap.Dispose()
    $stream.Dispose()
    return ($lines -join "`n")
}

New-Item -ItemType Directory -Force -Path $Out | Out-Null

foreach ($dir in Get-ChildItem $Root -Directory) {
    $files = Get-ChildItem $dir.FullName -Filter *.png | Sort-Object Name
    if ($Limit -gt 0) { $files = $files | Select-Object -First $Limit }
    $outPath = Join-Path $Out ("{0}_ocr.txt" -f $dir.Name)
    $parts = @()
    $empty = 0
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    foreach ($f in $files) {
        $text = ""
        try { $text = Get-OcrText $f.FullName } catch { Write-Host ("  ошибка {0}: {1}" -f $f.Name, $_) -ForegroundColor Yellow }
        if ([string]::IsNullOrWhiteSpace($text)) { $empty++ }
        $parts += ("--- стр. {0} ---`n{1}" -f $f.BaseName, $text)
    }
    $parts -join "`n`n" | Set-Content -Path $outPath -Encoding UTF8
    $sw.Stop()
    Write-Host ("{0}: {1} страниц, пустых {2}, {3:N1} c -> {4}" -f $dir.Name, $files.Count, $empty, $sw.Elapsed.TotalSeconds, $outPath)
}
