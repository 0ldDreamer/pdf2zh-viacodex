# SPDX-License-Identifier: AGPL-3.0-or-later
# Missing launcher runtimes are expected probe failures, including on PowerShell 5.1.
function Invoke-SetupPythonProbe {
    param([string]$Command, [string[]]$Arguments=@())
    $ErrorActionPreference='SilentlyContinue'
    $PSNativeCommandUseErrorActionPreference=$false
    $probe='import sys; print(sys.executable); sys.exit(0 if (3,11)<=sys.version_info[:2]<=(3,12) else 1)'
    try {
        $found=@(& $Command @Arguments -c $probe 2>$null)
        if ($LASTEXITCODE -eq 0 -and $found.Count -eq 1 -and
            (Test-Path -LiteralPath ([string]$found[0]) -PathType Leaf)) {
            return [string]$found[0]
        }
    } catch {
        # An unavailable executable or runtime must not abort automatic discovery.
    }
    return $null
}

function Find-SetupPython {
    param([string]$PythonExe)
    if ($PythonExe) {
        $found=Invoke-SetupPythonProbe -Command $PythonExe
        if (-not $found) { throw 'The specified Python is unavailable or unsupported. Use Python 3.11 or 3.12 with Tcl/Tk.' }
        return $found
    }
    $launcher=Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($version in @('-3.12','-3.11')) {
            $found=Invoke-SetupPythonProbe -Command $launcher.Source -Arguments @($version)
            if ($found) { return $found }
        }
    }
    $python=Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $found=Invoke-SetupPythonProbe -Command $python.Source
        if ($found) { return $found }
    }
    throw 'No supported Python found. Install Python 3.11 or 3.12 from https://www.python.org/downloads/windows/ with Tcl/Tk and the Python launcher, then rerun the dependency installer.'
}
