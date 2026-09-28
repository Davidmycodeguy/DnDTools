# Windows built-in OCR (Windows.Media.Ocr) worker for DnDTools' hover values.
# Reads one image path per stdin line and answers one JSON line:
#   {"ok": true, "lines": [{"text": "...", "x": 0, "y": 0, "w": 0, "h": 0}, ...]}
# Runs in Windows PowerShell 5.1, which ships with Windows 10/11; nothing to install.
$ErrorActionPreference = 'Stop'
# UTF-8 both ways: OCR returns long dashes (U+2014) for minus signs, and paths may hold non-ASCII names.
$utf8 = New-Object System.Text.UTF8Encoding $false
$stdout = New-Object System.IO.StreamWriter([Console]::OpenStandardOutput(), $utf8)
$stdout.AutoFlush = $true
$stdin = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), $utf8)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]

$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]

function Await($operation, [Type]$type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($operation))
    $task.Wait() | Out-Null
    $task.Result
}

function Read-Lines([string]$path) {
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    try {
        $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    }
    finally {
        $stream.Dispose()
    }
    $lines = @()
    foreach ($line in $result.Lines) {
        $left = [double]::MaxValue; $top = [double]::MaxValue; $right = 0.0; $bottom = 0.0
        foreach ($word in $line.Words) {
            $box = $word.BoundingRect
            $left = [Math]::Min($left, $box.X); $top = [Math]::Min($top, $box.Y)
            $right = [Math]::Max($right, $box.X + $box.Width); $bottom = [Math]::Max($bottom, $box.Y + $box.Height)
        }
        $lines += @{ text = $line.Text; x = [int]$left; y = [int]$top; w = [int]($right - $left); h = [int]($bottom - $top) }
    }
    return $lines
}

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) {
    $stdout.WriteLine((@{ ok = $false; error = 'Windows has no OCR language installed' } | ConvertTo-Json -Compress))
    exit 1
}
$stdout.WriteLine((@{ ok = $true; ready = $true; language = $engine.RecognizerLanguage.LanguageTag } | ConvertTo-Json -Compress))

while ($true) {
    $path = $stdin.ReadLine()
    if ($null -eq $path -or $path -eq 'exit') { break }
    try {
        $answer = @{ ok = $true; lines = @(Read-Lines $path) }
    }
    catch {
        $answer = @{ ok = $false; error = $_.Exception.Message }
    }
    $stdout.WriteLine(($answer | ConvertTo-Json -Compress -Depth 4))
}
