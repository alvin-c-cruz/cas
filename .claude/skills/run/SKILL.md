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

**3. Start Flask server detached (with auto-reload)**

Launch the server as a **detached** process via `Start-Process` — NOT as a harness-tracked
`run_in_background` task. The Werkzeug auto-reloader works by re-exec'ing itself (a supervisor
parent + a child that binds the port); a harness-tracked background task can't host that
re-exec and exits 255, killing the server. A detached process is owned by the OS instead of the
harness, so the reloader's parent/child cycle runs normally and **edits hot-reload**. Output goes
to a log file (not the harness) — read it in step 4/6 if the server misbehaves.

Use a normal (foreground) PowerShell call — `Start-Process` returns immediately and the server
keeps running detached:

```powershell
$log = "$env:TEMP\cas_server.out.log"; $err = "$env:TEMP\cas_server.err.log"
Start-Process -FilePath python -ArgumentList 'flask_app.py' -WorkingDirectory 'C:\envs\cas' `
    -RedirectStandardOutput $log -RedirectStandardError $err -WindowStyle Hidden
"Launched detached server (reloader on); logs: $log / $err"
```

(`flask_app.py` runs with `debug=True` → reloader ON. After a code edit, Werkzeug detects the
change and respawns the child automatically — no need to re-run /run. The reloader supervisor is
a python parent of the port-5050 listener, which step 2 already kills on the next /run.)

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
- If server fails to start, read the log files (`$env:TEMP\cas_server.out.log` and `.err.log`) and report them verbatim.
- **Auto-reload:** the detached server hot-reloads on code edits (Werkzeug reloader). You normally do NOT need to re-run /run after editing app code — just refresh the page. Re-run /run only if the server died or the port was taken. Static-asset edits still need a `?v=N` cache-buster bump (see CLAUDE.md), reload or not.
