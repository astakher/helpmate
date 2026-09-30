<#
.SYNOPSIS
  Download the speech models for SPEECH_ENGINE=real (Workstream C). Run once per machine.

  - Kokoro TTS (kokoro-onnx, release model-files-v1.1): kokoro-v1.0.onnx (fp32, 325 MB) and
    voices-v1.0.bin (28 MB) into services/speech/models/ (git-ignored). Not the int8 file: on the
    XPS's i7-8750H (no AVX-512 VNNI) int8 ran 10x slower, 9.4 s vs 0.98 s for 2.4 s of speech.
  - faster-whisper STT: pre-downloads the Whisper model named in .env (SPEECH_WHISPER_MODEL,
    default "base", ~145 MB) into the Hugging Face cache, so the first start is quick.

.EXAMPLE
  ./scripts/get_models.ps1
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$speech = Join-Path $root "services\speech"
$models = Join-Path $speech "models"
New-Item -ItemType Directory -Force $models | Out-Null

$release = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
$files = @(
  @{ name = "kokoro-v1.0.onnx"; bytes = 325505369 },
  @{ name = "voices-v1.0.bin"; bytes = 28214398 }
)
foreach ($f in $files) {
  $target = Join-Path $models $f.name
  if ((Test-Path $target) -and (Get-Item $target).Length -eq $f.bytes) {
    Write-Host "  $($f.name) already downloaded"
    continue
  }
  Write-Host "  downloading $($f.name) ($([math]::Round($f.bytes / 1MB)) MB)..."
  $ProgressPreference = "SilentlyContinue"   # the progress bar makes Invoke-WebRequest very slow
  Invoke-WebRequest "$release/$($f.name)" -OutFile "$target.part"
  if ((Get-Item "$target.part").Length -ne $f.bytes) {
    Remove-Item "$target.part"
    throw "$($f.name): unexpected size, download incomplete. Run the script again."
  }
  Move-Item -Force "$target.part" $target
}

$whisper = "base"
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
  $line = Select-String -Path $envFile -Pattern '^SPEECH_WHISPER_MODEL=(\S+)' | Select-Object -First 1
  if ($line) { $whisper = $line.Matches[0].Groups[1].Value }
}
Write-Host "  fetching Whisper model '$whisper' (first time only)..."
Push-Location $speech
try {
  uv sync --extra real --quiet
  uv run python -c "from faster_whisper import WhisperModel; WhisperModel('$whisper', device='cpu', compute_type='int8')"
} finally {
  Pop-Location
}
Write-Host "`nDone. Set SPEECH_ENGINE=real, HELPMATE_STT=http and HELPMATE_TTS=http in .env, then restart." -ForegroundColor Green
