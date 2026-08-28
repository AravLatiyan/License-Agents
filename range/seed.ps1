$ErrorActionPreference = "Stop"

$MailpitUrl = if ($env:MAILPIT_URL) {
    $env:MAILPIT_URL
} else {
    "http://localhost:8025"
}

$FixturesDir = Join-Path $PSScriptRoot "fixtures"

$fixtures = @(
    Get-ChildItem (Join-Path $FixturesDir "malicious") -Filter "*.json" |
        Sort-Object Name
    Get-ChildItem (Join-Path $FixturesDir "legitimate") -Filter "*.json" |
        Sort-Object Name
)

$count = 0

foreach ($fixture in $fixtures) {
    $body = Get-Content $fixture.FullName -Raw
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($body)

    $response = Invoke-RestMethod `
        -Uri "$MailpitUrl/api/v1/send" `
        -Method Post `
        -ContentType "application/json; charset=utf-8" `
        -Body $bytes

    $count++
    Write-Host "Seeded $($fixture.Name) [$($response.ID)]"
}
if ($count -eq 0) {
    Write-Error "Error: no Range fixture files found."
    exit 1
}
Write-Host ""
Write-Host "Seeded $count Range fixtures into Mailpit."