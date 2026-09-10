# Generates mosquitto/config/mosquitto.passwd (git-ignored) from the
# credentials in .env, using the mosquitto_passwd tool bundled in the
# eclipse-mosquitto Docker image so no local Mosquitto install is needed.
#
# Usage: .\scripts\generate_mosquitto_passwd.ps1
# Requires: .env (copy from .env.example first), Docker.

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path ".env")) {
    Write-Error "error: .env not found - copy .env.example to .env and fill in credentials first"
    exit 1
}

$envVars = @{}
Get-Content ".env" | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
        $envVars[$Matches[1]] = $Matches[2]
    }
}

foreach ($name in @("MQTT_DEVICE_USERNAME", "MQTT_DEVICE_PASSWORD", "MQTT_AUTOMATION_USERNAME", "MQTT_AUTOMATION_PASSWORD")) {
    if (-not $envVars.ContainsKey($name) -or [string]::IsNullOrWhiteSpace($envVars[$name])) {
        Write-Error "error: $name not set in .env"
        exit 1
    }
}

New-Item -ItemType Directory -Force -Path "mosquitto\config" | Out-Null
Remove-Item -Force -ErrorAction SilentlyContinue "mosquitto\config\mosquitto.passwd"

$configPath = (Resolve-Path "mosquitto\config").Path

docker run --rm -v "${configPath}:/mosquitto/config" eclipse-mosquitto:2 `
    mosquitto_passwd -b -c /mosquitto/config/mosquitto.passwd $envVars["MQTT_DEVICE_USERNAME"] $envVars["MQTT_DEVICE_PASSWORD"]

docker run --rm -v "${configPath}:/mosquitto/config" eclipse-mosquitto:2 `
    mosquitto_passwd -b /mosquitto/config/mosquitto.passwd $envVars["MQTT_AUTOMATION_USERNAME"] $envVars["MQTT_AUTOMATION_PASSWORD"]

Write-Output "Wrote mosquitto/config/mosquitto.passwd for users: $($envVars['MQTT_DEVICE_USERNAME']), $($envVars['MQTT_AUTOMATION_USERNAME'])"
