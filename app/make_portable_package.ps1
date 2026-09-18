$ErrorActionPreference = "Stop"

# Only this explicit allowlist is packaged. Runtime data and credentials are excluded.
$toolDirectory = Split-Path -Parent $PSScriptRoot
$rootFiles = @('START.cmd', 'README.md')
$appFiles = @(
    'START.ps1', 'CODEX_TASK.md',
    'new_triage_job.ps1', 'new_triage_job.cmd',
    'setup_mcp.ps1', 'setup_mcp.cmd', 'start_svacer_http.ps1', 'start_svacer_http.py',
    'start_svacer_http.cmd', 'restart_svacer_http.ps1', 'restart_svacer_http.cmd',
    'stop_components.ps1', 'STOP SVACER.cmd', 'STOP ANALYZE.cmd', 'STOP ALL.cmd',
    'triage_dashboard.py', 'triage_dashboard.ps1', 'triage_dashboard.cmd',
    'make_portable_package.ps1', 'make_portable_package.cmd',
    'triage_queue.py', 'make_mcp_decisions_template.py', 'validate_mcp_decisions.py',
    'export_decisions_csv.py', 'extract_gost_markers.py', 'run_extractor.cmd',
    'make_decisions_template.py', 'validate_decisions.py', 'svacer-settings.json',
    'svacer-mcp/pyproject.toml', 'svacer-mcp/LICENSE', 'svacer-mcp/README.md'
)
$modules = @(
    '__init__.py', 'server.py', 'exceptions.py', 'config.py', 'auth_token.py',
    'auth.py', 'api_client.py', 'utils/__init__.py', 'utils/validators.py',
    'utils/response.py', 'utils/filters.py', 'tools/__init__.py',
    'tools/warnings.py', 'tools/stats.py', 'tools/snapshots.py',
    'tools/project_groups.py', 'tools/projects.py', 'tools/markers.py',
    'tools/file_preview.py', 'tools/diff.py', 'tools/descriptions.py',
    'tools/markup_import.py'
)
$files = @($rootFiles) + @($appFiles | ForEach-Object { "app/$_" }) +
    @($modules | ForEach-Object { "app/svacer-mcp/svacer_mcp/$_" })
$rootPath = [IO.Path]::GetFullPath($toolDirectory)

foreach ($relative in $files) {
    $item = Get-Item -LiteralPath (Join-Path $rootPath $relative)
    if ($item.PSIsContainer) { throw "Expected file: $relative" }
    $node = $item
    while ($node -and $node.FullName -ne $rootPath) {
        if ($node.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Package input must not be a link: $relative"
        }
        if ($node -is [IO.FileInfo]) { $node = $node.Directory } else { $node = $node.Parent }
    }
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$stamp = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$archiveDirectory = Join-Path $toolDirectory "ARCHIVE"
if (-not (Test-Path -LiteralPath $archiveDirectory)) {
    New-Item -ItemType Directory -Path $archiveDirectory | Out-Null
}
$archivePath = Join-Path $archiveDirectory "svacer_gost_triage_portable_$stamp.zip"
$archiveStream = [IO.File]::Open($archivePath, [IO.FileMode]::CreateNew)
try {
    $zip = New-Object IO.Compression.ZipArchive($archiveStream, [IO.Compression.ZipArchiveMode]::Create, $true)
    try {
        $null = $zip.CreateEntry("svacer_gost_triage/RESULTS/")
        foreach ($relative in $files) {
            $null = [IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $zip, (Join-Path $rootPath $relative),
                "svacer_gost_triage/$relative", [IO.Compression.CompressionLevel]::Optimal)
        }
    }
    finally { $zip.Dispose() }
}
catch {
    Write-Warning 'Packaging failed. Do not distribute the incomplete ZIP.'
    throw
}
finally { $archiveStream.Dispose() }
Write-Host "Переносимый архив создан: $archivePath"
Write-Host "На другом компьютере распакуйте архив и запустите только START.cmd"
