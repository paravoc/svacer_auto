param(
    [string]$SnapshotUrl,
    [string]$RepositoryUrl,
    [string]$GitRef,
    [switch]$NoClipboard,
    [switch]$NoOpen,
    [switch]$NoDashboard
)

$ErrorActionPreference = "Stop"
$toolDirectory = Split-Path -Parent $PSScriptRoot
$settingsPath = Join-Path $PSScriptRoot "svacer-settings.json"
if (-not (Test-Path -LiteralPath $settingsPath)) {
    throw "Не найден файл настроек: $settingsPath"
}
$settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
$filterName = [string]$settings.filter_name
$advancedFilter = [string]$settings.advanced_filter
$parallelWorkers = [int]$settings.parallel_workers
$batchSize = [int]$settings.batch_size
$runMode = [string]$settings.run_mode
$verificationEnabled = [bool]$settings.verification_enabled
$verificationVerdicts = @($settings.verification_verdicts | ForEach-Object { [string]$_ })
$verificationWorkers = [int]$settings.verification_workers
$tokenWarning = [int]$settings.saved_context_token_warning
if ([string]::IsNullOrWhiteSpace($filterName)) {
    throw "В svacer-settings.json не задан filter_name"
}
if ($advancedFilter -cne 'filter(markers, "ГОСТ 71207-2024" in .checker_labels)') {
    throw "В svacer-settings.json должен быть точный фильтр ГОСТ 71207-2024"
}
if ($parallelWorkers -lt 1 -or $parallelWorkers -gt 8) {
    throw "parallel_workers должен быть от 1 до 8"
}
if ($batchSize -lt 1 -or $batchSize -gt 50) {
    throw "batch_size должен быть от 1 до 50"
}
if ($runMode -notin @('single_batch', 'until_complete')) {
    throw "run_mode должен быть single_batch или until_complete"
}
if ($verificationWorkers -lt 1 -or $verificationWorkers -gt 8) {
    throw "verification_workers должен быть от 1 до 8"
}
if (-not $verificationEnabled) {
    throw "verification_enabled должен быть true: Confirmed нельзя импортировать без независимой проверки"
}
if ($verificationVerdicts.Count -ne 1 -or $verificationVerdicts[0] -cne "Confirmed") {
    throw "verification_verdicts должен содержать только Confirmed"
}
if ($tokenWarning -lt 0) {
    throw "saved_context_token_warning не может быть отрицательным"
}

if ([string]::IsNullOrWhiteSpace($SnapshotUrl)) {
    $SnapshotUrl = Read-Host "Вставьте ссылку на снимок Svacer"
}
if ([string]::IsNullOrWhiteSpace($RepositoryUrl)) {
    $RepositoryUrl = Read-Host "Вставьте URL Git-репозитория"
}
if ([string]::IsNullOrWhiteSpace($GitRef)) {
    $GitRef = Read-Host "Введите точный тег, ветку или commit"
}

if ([string]::IsNullOrWhiteSpace($SnapshotUrl) -or
    [string]::IsNullOrWhiteSpace($RepositoryUrl) -or
    [string]::IsNullOrWhiteSpace($GitRef)) {
    throw "Все три значения обязательны."
}
$snapshotUri = $null
$serverUri = $null
if (-not [Uri]::TryCreate($SnapshotUrl.Trim(), [UriKind]::Absolute, [ref]$snapshotUri) -or
    $snapshotUri.Scheme -notin @('http', 'https') -or $snapshotUri.UserInfo) {
    throw "Нужна полная http/https ссылка на снимок без пароля или токена в URL."
}
if (-not [Uri]::TryCreate([string]$settings.svacer_url, [UriKind]::Absolute, [ref]$serverUri) -or
    $snapshotUri.Authority -ne $serverUri.Authority -or $snapshotUri.Scheme -ne $serverUri.Scheme) {
    throw "Сервер ссылки не совпадает с svacer_url в svacer-settings.json. Исправьте настройку и перезапустите MCP."
}
$uuid = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
$snapshotMatch = [regex]::Match($snapshotUri.AbsolutePath, "/project/($uuid)/branch/($uuid)/snapshot/($uuid)(?:/|$)")
if (-not $snapshotMatch.Success) {
    throw "Ссылка не похожа на ссылку снимка Svacer: отсутствуют UUID project/branch/snapshot."
}

$stamp = (Get-Date -Format "yyyyMMdd-HHmmss") + "-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
$jobDir = Join-Path (Join-Path $toolDirectory "RESULTS") $stamp
$null = New-Item -ItemType Directory -Path $jobDir
$null = New-Item -ItemType Directory -Path (Join-Path $jobDir "raw") -Force
$null = New-Item -ItemType Directory -Path (Join-Path $jobDir "notes") -Force

$job = [ordered]@{
    snapshot_url = $SnapshotUrl.Trim()
    project_id = $snapshotMatch.Groups[1].Value
    branch_id = $snapshotMatch.Groups[2].Value
    snapshot_id = $snapshotMatch.Groups[3].Value
    repository_url = $RepositoryUrl.Trim()
    git_ref = $GitRef.Trim()
    filter_name = $filterName
    advanced_filter = $advancedFilter
    parallel_workers = $parallelWorkers
    batch_size = $batchSize
    run_mode = $runMode
    verification_enabled = $verificationEnabled
    verification_verdicts = $verificationVerdicts
    verification_workers = $verificationWorkers
    saved_context_token_warning = $tokenWarning
    tool_directory = $toolDirectory
    app_directory = $PSScriptRoot
    job_directory = $jobDir
    created_at = (Get-Date).ToString("o")
}
$job | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $jobDir "job.json") -Encoding UTF8

$taskPath = Join-Path $PSScriptRoot "CODEX_TASK.md"
$prompt = @"
Выполни локальную разметку Svacer по инструкции:
$taskPath

Параметры задачи находятся здесь:
$(Join-Path $jobDir "job.json")

Используй MCP-сервер svacer. Анализируй только маркеры, прошедшие advanced_filter из job.json ($filterName). Выполняй анализ параллельно через подагентов по правилам CODEX_TASK.md. Сохрани итоговые decisions.jsonl и decisions.csv в каталог задачи. Подготовь предварительный файл импорта, но ничего не отправляй в Svacer без моего отдельного явного подтверждения точной фразой из preview.
"@
$promptPath = Join-Path $jobDir "START_PROMPT.txt"
$prompt | Set-Content -LiteralPath $promptPath -Encoding UTF8
if (-not $NoClipboard) {
    $prompt | Set-Clipboard
}

Write-Host ""
Write-Host "Задача создана: $jobDir"
$runModeText = if ($runMode -eq 'single_batch') { 'одна партия' } else { 'до завершения' }
Write-Host "Режим: $runModeText, до $parallelWorkers подагентов, партия $batchSize маркеров."
if (-not $NoClipboard) {
    Write-Host "Промпт скопирован в буфер обмена."
}
Write-Host "Промпт также сохранён: $promptPath"
if (-not $NoClipboard) { Write-Host "Открой новую задачу Codex и нажми Ctrl+V." }
Write-Host ""
if (-not $NoOpen) {
    Start-Process explorer.exe -ArgumentList @($jobDir)
}
if (-not $NoDashboard) {
    $dashboardScript = Join-Path $PSScriptRoot "triage_gui.ps1"
    $dashboardArguments = "-NoLogo -NoProfile -ExecutionPolicy Bypass -File `"$dashboardScript`" -JobDirectory `"$jobDir`""
    # The user explicitly requested a visible interactive graphical dashboard.
    Start-Process -FilePath "powershell.exe" -ArgumentList $dashboardArguments
}
