# Post-Update / Post-Doctor Cleanup

Nach einem `hermes update` + `hermes doctor fix` bleiben **immer** Residual-Issues,
die der Doctor nicht automatisch behebt. Dieses Reference dokumentiert die
wiederkehrenden Muster.

---

## Checkliste nach `hermes doctor fix`

### 1. Orphan Alias Wrapper prüfen

Wrapper-Skripte in `~/.local/bin/hermes-*` können auf Profile zeigen, die
gelöscht oder umbenannt wurden.

**Diagnose:**
```bash
# Alle Wrapper anzeigen
ls -la ~/.local/bin/hermes-*

# Inhalt prüfen — zeigt das -p target
cat ~/.local/bin/hermes-*
```

**Erwartete Targets:**
- `hermes-news` → `-p hermes-news`
- `hermes_lang` → `-p hermes_lang`
- `hermes_trading` → `-p hermes_trading` (NICHT `hermes-trading`)
- `hermes-02` → `-p hermes-02` (wenn Profil existiert)

**Fix — Orphan entfernen (Profil existiert nicht mehr):**
```bash
rm ~/.local/bin/hermes-<orphan-name>
```

**Fix — Falsches Target (dash statt underscore):**
```bash
# Korrektur via sed
sed -i 's/exec hermes -p hermes-trading/exec hermes -p hermes_trading/' ~/.local/bin/hermes_trading
```

**Alternative — Korrekte Anlage via `hermes profile alias`:**
```bash
# Wrapper korrekt anlegen (statt manuelles Skript)
hermes profile alias --name <alias-name> <profile-name>
```

### 2. Deprecated Toolset Names in Config

Der Doctor warnt vor unbekannten Toolset-Namen in `platform_toolsets`, z.B.:
```
⚠ platform 'cli' references unknown toolset 'messaging' — did you mean 'hermes-cli'?
```

**Fix:**
```bash
sed -i 's/- messaging/- hermes-cli/' ~/.hermes/config.yaml
```

Betroffene Stelle: `platform_toolsets.cli` Liste. Der Name `messaging` wurde
in neueren Versionen zu `hermes-cli` umbenannt.

### 3. Profil-Status prüfen

```bash
hermes profile list
```

Achte auf:
- **Gateway running?** — Profile ohne laufenden Gateway haben keine Cron-Ticks
- **Missing config?** — Profile ohne `config.yaml` nutzen globale Defaults, können
  aber kein eigenes Modell setzen. Doctor flaggt das als ⚠, ist aber kein Bug
  wenn das Profil bewusst ohne Config läuft.
- **Orphan Aliases** — vom Doctor als `⚠ Orphan alias: X → profile 'Y' no longer exists`
  gemeldet. Siehe Schritt 1.

### 4. Config-Version bestätigen

```bash
grep _config_version ~/.hermes/config.yaml
```

Sollte auf die aktuelle Version zeigen (z.B. `33`). Der Doctor migriert das
automatisch, aber prüfen schadet nicht.

---

## Typische Doctor-Fix-Resultate

| Was der Doctor fixte | Was er NICHT fixte | Handlungsbedarf |
|---|---|---|
| Config-Migration (v30→v33) | Orphan Aliases | Manuell prüfen/entfernen |
| API-Connectivity-Test | Deprecated Toolset-Namen | `sed`-Fix |
| Package-Checks | Falsche Wrapper-Targets | Wrapper-Content prüfen |
| Directory-Structure | Missing Profile Configs | Optional (nicht kritisch) |

---

## Prävention: Nach jedem Update

```bash
# 1. Doctor laufen lassen
hermes doctor fix

# 2. Residual-Checkliste abarbeiten
ls -la ~/.local/bin/hermes-*
hermes profile list
grep _config_version ~/.hermes/config.yaml
```