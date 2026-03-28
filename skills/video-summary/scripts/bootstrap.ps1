$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py "$scriptDir/bootstrap.py" @args
    exit $LASTEXITCODE
}

if (Get-Command python -ErrorAction SilentlyContinue) {
    & python "$scriptDir/bootstrap.py" @args
    exit $LASTEXITCODE
}

Write-Error "Python 3.10+ is required to bootstrap video-summary."
exit 1
