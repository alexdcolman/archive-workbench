param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("SelectPort", "WaitReady")]
    [string]$Action,
    [string]$PortFile,
    [int]$Port = 8501,
    [string]$Service = "app-cpu"
)

$ErrorActionPreference = "Stop"

function Test-LoopbackPortAvailable([int]$CandidatePort) {
    $listener = $null
    try {
        $listener = [System.Net.Sockets.TcpListener]::new(
            [System.Net.IPAddress]::Loopback,
            $CandidatePort
        )
        $listener.Start()
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($null -ne $listener) {
            try { $listener.Stop() } catch { }
        }
    }
}

function Find-DockerPortOwner([int]$CandidatePort) {
    try {
        $lines = & docker ps --format "{{.Names}}|{{.Ports}}" 2>$null
    }
    catch {
        return $null
    }
    foreach ($line in $lines) {
        $parts = [string]$line -split "\|", 2
        if ($parts.Count -ne 2) { continue }
        $ports = $parts[1]
        $pattern = "(?:127\.0\.0\.1|0\.0\.0\.0|\[::\]):$CandidatePort->"
        if ($ports -match $pattern) { return $parts[0] }
    }
    return $null
}

if ($Action -eq "SelectPort") {
    if ([string]::IsNullOrWhiteSpace($PortFile)) {
        Write-Error "SelectPort requiere PortFile."
        exit 2
    }

    $selected = $null
    if (Test-LoopbackPortAvailable 8501) {
        $selected = 8501
    }
    else {
        $owner = Find-DockerPortOwner 8501
        Write-Host ""
        if ($owner) {
            Write-Host "El puerto 8501 ya está en uso por el contenedor Docker '$owner'."
        }
        else {
            Write-Host "El puerto 8501 ya está en uso por otra aplicación de esta computadora."
        }
        Write-Host "Archive Workbench no va a detener ni modificar ese proceso."

        foreach ($candidate in 8502..8510) {
            if (Test-LoopbackPortAvailable $candidate) {
                $selected = $candidate
                break
            }
        }
        if ($null -eq $selected) {
            Write-Host "No encontré un puerto libre entre 8502 y 8510 para iniciar Archive Workbench."
            exit 3
        }
        Write-Host "Se usará el puerto alternativo $selected para esta ejecución."
    }

    Set-Content -LiteralPath $PortFile -Value ([string]$selected) -Encoding Ascii
    exit 0
}

$healthUrl = "http://127.0.0.1:$Port/_stcore/health"
for ($attempt = 0; $attempt -lt 90; $attempt++) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri $healthUrl
        if ($response.StatusCode -eq 200 -and ([string]$response.Content).Trim() -eq "ok") {
            exit 0
        }
    }
    catch { }

    try {
        $containerId = (& docker compose ps -q $Service 2>$null | Select-Object -First 1)
        if ($containerId) {
            $status = (& docker inspect --format "{{.State.Status}}" $containerId 2>$null | Select-Object -First 1)
            if ($status -in @("exited", "dead")) {
                Write-Host "Archive Workbench se detuvo antes de quedar disponible en el navegador."
                exit 4
            }
        }
    }
    catch { }

    Start-Sleep -Seconds 2
}

Write-Host "Archive Workbench no respondió a su comprobación de salud en $healthUrl."
exit 1
