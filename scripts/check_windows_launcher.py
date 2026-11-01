"""Exercise Windows launcher orchestration with a mock Docker CLI, no deployment."""
import json
import subprocess
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='pes-launcher-') as folder:
    temp = Path(folder)
    (temp / 'deploy.ps1').write_bytes((root / 'deploy.ps1').read_bytes())
    (temp / 'deploy.env.example').write_text('PORTAL_IMAGE=ghcr.io/pradanain/pesse2026:latest\nTRAEFIK_NETWORK=proxy\n')
    seed = temp / 'private/seed'; seed.mkdir(parents=True)
    for name in ('portal.sqlite3', 'secret.key', 'manifest.json'):
        (seed / name).write_text('synthetic-mock-only')
    runner = temp / 'test.ps1'
    runner.write_text(r'''
param([switch]$ForcePull, [switch]$BadNetwork)
$global:calls = New-Object 'System.Collections.Generic.List[string]'
$global:rejectNetwork = [bool]$BadNetwork
function global:docker {
    $global:calls.Add(($args -join ' '))
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'info') { Write-Output 'linux' }
    if ($args[0] -eq 'network' -and $global:rejectNetwork) { $global:LASTEXITCODE = 1 }
}
if ($ForcePull) { & "$PSScriptRoot/deploy.ps1" -Pull } else { & "$PSScriptRoot/deploy.ps1" }
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$global:calls | ConvertTo-Json | Set-Content -LiteralPath "$PSScriptRoot/calls.json"
''', encoding='utf-8')
    def run(*args):
        return subprocess.run(['powershell', '-NoProfile', '-File', str(runner), *args], capture_output=True, text=True)
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    calls = json.loads((temp / 'calls.json').read_text(encoding='utf-8-sig'))
    assert any('compose --env-file deploy.env -f compose.server.yml pull' == x for x in calls)
    assert any(' up -d --pull never --wait --wait-timeout 180' in x for x in calls)
    (temp / 'images').mkdir(); (temp / 'images/portal-amd64.tar').write_text('synthetic mock')
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    calls = json.loads((temp / 'calls.json').read_text(encoding='utf-8-sig'))
    assert 'load -i images/portal-amd64.tar' in calls
    assert not any(x.endswith(' pull') for x in calls)
    result = run('-ForcePull')
    assert result.returncode == 0, result.stdout + result.stderr
    calls = json.loads((temp / 'calls.json').read_text(encoding='utf-8-sig'))
    assert not any(x.startswith('load ') for x in calls)
    assert any(x.endswith(' pull') for x in calls)
    result = run('-BadNetwork')
    assert result.returncode == 1 and 'Network Traefik' in result.stdout, (result.returncode, result.stdout, result.stderr)
print('Windows launcher: pull, offline image, forced pull and missing-network handling passed; no real Docker mutations.')
