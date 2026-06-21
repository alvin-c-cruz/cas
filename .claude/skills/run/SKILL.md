---
name: run
description: Use when the user types /run or asks to start the CAS Flask dev server. Kills existing servers first, starts a fresh one, opens Playwright.
---

# /run — Fresh Dev Server + Playwright

Kills any existing processes on port 5050, starts a clean Flask server, waits for it to respond, then opens Playwright at `http://127.0.0.1:5050`.

## Steps

**1. Close the Playwright browser (if open)**

```
mcp__playwright__browser_close
```

Ignore errors if no browser is open.

**2. Kill ONLY the CAS server on port 5050**

⚠️ Do NOT kill all python (`Get-Process -Name python | Stop-Process`) — the user runs other
Flask apps (e.g. invoicing on :7000, production on :9000). Kill only the process bound to
**port 5050**, plus its reloader parent (Flask's auto-reloader runs a parent + a child that
binds the port; killing just the child lets the parent respawn it, so kill the python parent too):

```powershell
$pids = @(Get-NetTCPConnection -LocalPort 5050 -State Listen -ErrorAction SilentlyContinue |
          Select-Object -Expand OwningProcess -Unique)
foreach ($procId in $pids) {
    $parent = (Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue).ParentProcessId
    taskkill /PID $procId /T /F *> $null
    if ($parent -and (Get-Process -Id $parent -ErrorAction SilentlyContinue).ProcessName -eq 'python') {
        taskkill /PID $parent /T /F *> $null   # stop the reloader so it can't respawn
    }
}
```
(`$procId`, not `$pid` — `$pid` is a reserved PowerShell automatic variable.) If the assistant
started the server as a tracked background task, prefer stopping THAT task instead of killing by port.

Wait 2 seconds, then verify using `Get-NetTCPConnection` (more accurate than `netstat`):

```powershell
Start-Sleep 2
$conn = Get-NetTCPConnection -LocalPort 5050 -State Listen -ErrorAction SilentlyContinue
if ($conn) { Write-Host "WARNING: port 5050 still in use by PID $($conn.OwningProcess)" } else { Write-Host "Port 5050 is free" }
```

**3. Start Flask server in background**

Use PowerShell tool with `run_in_background: true`. Launch **without the auto-reloader** —
`python flask_app.py` runs the reloader, which re-execs itself; under `run_in_background` the
tracked process then exits 255 and kills the server (false "failed" / dead server). Running with
`use_reloader=False` is one stable process the harness tracks correctly:

```powershell
python -c "from dotenv import load_dotenv; load_dotenv(); from app import create_app; create_app().run(host='127.0.0.1', port=5050, use_reloader=False)"
```

(Trade-off: no auto-reload on code edits — fine for a session; just re-run step 2+3 after code
changes. If you want live reload, run `python flask_app.py` yourself in a foreground terminal.)

**4. Poll until server responds**

```powershell
$max = 15; $i = 0
while ($i -lt $max) {
    try { Invoke-WebRequest http://127.0.0.1:5050 -UseBasicParsing -TimeoutSec 2 | Out-Null; break }
    catch { Start-Sleep 1; $i++ }
}
if ($i -eq $max) { Write-Host "Server did not start in time" } else { Write-Host "Server ready" }
```

**5. Navigate Playwright to the app**

```
mcp__playwright__browser_navigate  url=http://127.0.0.1:5050
mcp__playwright__browser_snapshot
```

**6. Report status**

Tell the user: how many PIDs were killed, whether server started cleanly, current page URL/title.

## Notes

- Run from the project root (session working directory is already correct).
- **Worktree sessions:** if Flask fails with `SECRET_KEY must be set`, copy `.env` from `C:\envs\cas\.env` to the worktree root before retrying.
- If port 5050 is still occupied after kill, report remaining PIDs.
- Redirect to `/login` is expected — not an error.
- If server fails to start, read the background task output file and report it verbatim.
