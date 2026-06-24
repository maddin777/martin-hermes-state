# Bisync Diagnostic — "Meine Änderungen sind nicht auf dem Server"

## Symptom

User sagt: "Ich finde nicht meine aktuellsten Einträge" / "Das Wiki ist veraltet" / Sync scheint nicht zu funktionieren.

## Drei-Schritte-Diagnose

### 1. Check ob Bisync überhaupt läuft

```bash
hermes cron list | grep bisync
# → f5eb3bfaf65e, schedule 0 2 * * *, last_status: ok/error
```

Wenn `last_status` nicht `ok` ist → Logs prüfen:
```bash
cat /root/.hermes/cron/output/f5eb3bfaf65e/$(ls -t /root/.hermes/cron/output/f5eb3bfaf65e/ | head -1)
```

### 2. Check ob die Dateien des Users auf GDrive existieren

Nicht fragen "hast du hochgeladen?" — einfach prüfen:

```bash
# Existiert die Datei auf GDrive?
export PATH="/root/.local/bin:$PATH"
timeout 20 rclone lsf gdrive:hermes-obsidian-vault/<pfad/zur/datei.md>

# Oder: komplette Liste neuerer Dateien
timeout 20 rclone lsf gdrive:hermes-obsidian-vault/hermes/ --max-depth 1
```

**Wenn die Datei NICHT auf GDrive ist** → Das Problem liegt auf dem User-Gerät (Obsidian Sync?, falscher GDrive-Ordner?, Desktop-App nicht verbunden?). Nichts am Server-Bisync ändern.

**Wenn die Datei AUF GDrive ist** → Bisync selbst hat sie nicht gezogen → Problem im Bisync-Script.

### 3. Dry-Run Bisync (jederzeit, ohne Risiko)

```bash
export PATH="/root/.local/bin:$PATH"
timeout 30 rclone bisync /root/obsidian-vault/ gdrive:hermes-obsidian-vault/ -v --dry-run 2>&1 | grep -E "Path2.*(changed|new|deleted)" | head -20
```

Interpretation:
- `Path2 File changed: time (newer) - <datei.md>` → User hat Datei editiert, Bisync würde sie ziehen ✅
- `Path2 File is new - <datei.md>` → Neue Datei vom User, Bisync würde sie ziehen ✅
- Keine Path2-Treffer außer `.obsidian/app.json` → **User hat keine Inhaltsdateien auf GDrive hochgeladen** ⚠️

### 4. Live-Bisync (wenn dry-run OK)

```bash
export PATH="/root/.local/bin:$PATH"
rclone bisync /root/obsidian-vault/ gdrive:hermes-obsidian-vault/ -v --progress 2>&1
```

## Häufige Ursachen ("Nicht der Bisync")

| Behauptung | Realität |
|-----------|----------|
| "Sync ist tot" | Bisync läuft täglich 02:00, last_status ok — nur nichts zu syncen |
| "Du hast nicht die aktuellen Einträge" | User nutzt Obsidian Sync (separate Cloud) → nie auf GDrive |
| "Ich hab doch geschrieben" | User sync von Gerät läuft nicht (Google Drive Desktop App tot, rclone manuell vergessen) |

## Script

`/root/.hermes/scripts/obsidian-bisync.sh`

- no_agent Cron, täglich 02:00
- Silent bei Erfolg (exit 0, kein Output)
- Auto-Resync bei `Must run --resync to recover`
- Output bei Fehler (wird via Cron-Delivery zugestellt)

## Exclude-Regeln (aktuell)

```
--exclude "*.conflict*"
--exclude "*conflict*"
--exclude ".DS_Store"
```

Konflikt-Dateien werden nicht gesynct. Wenn doch `.conflict1`-Dateien in der dry-run auftauchen, sind sie lokal neu entstanden (z.B. durch Obsidian Workspace-Konflikte) und nicht vom Bisync verursacht.