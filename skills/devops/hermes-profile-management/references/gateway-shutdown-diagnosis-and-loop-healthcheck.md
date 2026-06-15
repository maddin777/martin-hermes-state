# Gateway Shutdown Diagnosis & Loop Healthcheck

Session date: 2026-06-14
Trigger: Martin saw "gateway shutting down" and asked if it was a planned restart or a problem.

## Shutdown Diagnosis

### Planned vs. Unplanned

| Signal | Meaning | Action |
|--------|---------|--------|
| `signal=SIGTERM under_systemd=yes parent_cmdline=/sbin/init` | systemd-issued stop (weekly restart, manual `systemctl stop`) | None — planned |
| `signal=SIGTERM` *without* parent_cmdline=init | Manual kill or script-triggered | Check what initiated it |
| `code=killed, status=9/KILL` without prior SIGTERM | OOM or forced kill | Investigate |
| Python traceback before SIGTERM | Crash → systemd restart | Fix root cause |
| `Error while calling get_updates ... graceful shutdown` | Telegram lib quirk on shutdown | Harmless, suppress |

### Journalctl Command Reference

```bash
# Recent shutdowns (last 24h)
journalctl -u hermes-gateway.service --since "1 hour ago" | grep -i "shutdown\|SIGTERM\|killed"

# All shutdown events (14 days)
journalctl -u hermes-gateway.service --since "14 days ago" -p info | grep -i "shutdown\|SIGTERM"

# Crash/error investigation
journalctl -u hermes-gateway.service -n 50 | grep -E "ERROR|CRITICAL|Traceback|killed"
```

## Loop Healthcheck Configuration

### systemd Drop-In (`/etc/systemd/system/hermes-gateway.service.d/99-restart-limit.conf`)

Applied June 14, 2026 — changes from old defaults:

| Parameter | Old Value | New Value | Reason |
|-----------|-----------|-----------|--------|
| `Restart` | `on-failure` | `always` | Catch planned stops too (faster recovery from weekly restart) |
| `RestartSec` | 60s | 10s | Gateway back within seconds instead of a minute |
| `TimeoutStopSec` | 90s | 20s | SIGKILL after 20s instead of hanging 90s during weekly restart |
| `StartLimitBurst` | 3 | 3 (unchanged) | Still prevent infinite crash loops |
| `StartLimitIntervalSec` | 600 | 600 (unchanged) | 10min window for burst detection |

### Verification

```bash
systemctl show hermes-gateway.service | grep -E "Restart=|RestartUSec|TimeoutStopUSec"
# Should show: Restart=always, RestartUSec=10s, TimeoutStopUSec=20s
```

### Cron Watchdog

- Job ID: `eec953aecbd8`
- Schedule: `every 5m` (was `every 30m`)
- Script: `/root/.hermes/scripts/gateway-watchdog.py`
- `no_agent=True`, deliver: local
- Silent on success, logs to `/root/.hermes/logs/gateway-watchdog.log`
- Escalates: >2x same error in 60min → CRITICAL (no auto-restart)

### Weekly Restart Script

- Job ID: `fbc802343226`
- Schedule: `0 4 * * 0` (Sunday 04:00)
- Script: `/root/.hermes/scripts/weekly-gateway-restart.sh`
- Wait loop: 12 iterations × 2s = 24s (matches TimeoutStopSec=20s + buffer)

### Nächste Schritte (geplant)

- Keine — Config ist live, greift bei nächstem Stop/Crash.
- Nächste Gelegenheit zum Testen: nächster Sunday 04:00 (weekly restart) oder manueller `systemctl restart`.