---
name: run
description: Use when the user types /run or asks to start the CAS Flask dev server. Kills existing servers first, starts a fresh one, opens Playwright.
---

# /run — Fresh Dev Server + Playwright

Kills any existing processes on port 5000, starts a clean Flask server, waits for it to respond, then opens Playwright at `http://127.0.0.1:5000`.

## Steps

**1. Close the Playwright browser (if open)**

```
mcp__playwright__browser_close
```

Ignore errors if no browser is open.

**2. Kill any processes on port 5000**

Kill all Python processes at once — Flask's reloader respawns if you kill parent/child one at a time:

```powershell
Get-Process -Name python -ErrorAction SilentlyContinue | Stop-Process -Force
```

Wait 2 seconds, then verify using `Get-NetTCPConnection` (more accurate than `netstat`):

```powershell
Start-Sleep 2
$conn = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue
if ($conn) { Write-Host "WARNING: port 5000 still in use by PID $($conn.OwningProcess)" } else { Write-Host "Port 5000 is free" }
```

**3. Start Flask server in background**

Use PowerShell tool with `run_in_background: true`:

```powershell
python flask_app.py
```

**4. Poll until server responds**

```powershell
$max = 15; $i = 0
while ($i -lt $max) {
    try { Invoke-WebRequest http://127.0.0.1:5000 -UseBasicParsing -TimeoutSec 2 | Out-Null; break }
    catch { Start-Sleep 1; $i++ }
}
if ($i -eq $max) { Write-Host "Server did not start in time" } else { Write-Host "Server ready" }
```

**5. Navigate Playwright to the app**

```
mcp__playwright__browser_navigate  url=http://127.0.0.1:5000
mcp__playwright__browser_snapshot
```

**6. Report status**

Tell the user: how many PIDs were killed, whether server started cleanly, current page URL/title.

## Notes

- Run from the project root (session working directory is already correct).
- **Worktree sessions:** if Flask fails with `SECRET_KEY must be set`, copy `.env` from `C:\envs\cas\.env` to the worktree root before retrying.
- If port 5000 is still occupied after kill, report remaining PIDs.
- Redirect to `/login` is expected — not an error.
- If server fails to start, read the background task output file and report it verbatim.
