"""
Script 1: YouTube Channel Monitor
Holt Videos der letzten 5 Tage, extrahiert Transkripte, speichert in SQLite
"""
import sqlite3
import subprocess
import time
import sys
from datetime import datetime, timedelta, timezone

DB_PATH = "/root/.hermes/profiles/hermes_trading/skills/trading/data/trading.db"
DAYS = 5
SLEEP_BETWEEN_VIDEOS = 120  # 2 Minuten zwischen Transkript-Abrufen

CHANNELS = [
    ("mario lochner",   "https://www.youtube.com/@mario.lochner"),
    ("maxim investiert","https://www.youtube.com/@maximinvestiert"),
    ("tipp checker",    "https://www.youtube.com/@tipp-checker"),
    ("grey x capital",  "https://www.youtube.com/@GREYxCAPITAL"),
    ("moritz hessel",   "https://www.youtube.com/@moritz.hessel.official"),
    ("beating beta",    "https://www.youtube.com/@BeatingBeta_official"),
    ("techaktien",      "https://www.youtube.com/@Techaktien"),
    ("der Aktionaer",      "https://www.youtube.com/@der.aktionaer/videos"),
    ("ohne aktien wird schwer",      "https://www.youtube.com/@ohneaktienwirdschwer-podcast/videos"),
    ("Aktienfinder",      "https://www.youtube.com/@Aktienfinder/videos"),
    ("Ticker Symbol: YOU",      "https://www.youtube.com/@TickerSymbolYOU/videos"),
    ("markus koch closing bell",      "https://youtube.com/playlist?list=PLhYtU24OgOhrJVU5fsT3lPU6Wrqh5xc4L&si=VZ0xd9o_awG0nKEg"),
]

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            video_id    TEXT PRIMARY KEY,
            channel     TEXT,
            title       TEXT,
            upload_date TEXT,
            transcript  TEXT,
            status      TEXT DEFAULT 'pending',
            created_at  TEXT DEFAULT (datetime('now')),
            analyzed_at TEXT
        )
    """)
    con.commit()
    return con

def get_recent_video_ids(channel_url, days):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    # Nur /videos anhängen wenn URL nicht schon darauf endet und kein Playlist ist
    if channel_url.endswith("/videos") or "/playlist?" in channel_url:
        url = channel_url
    else:
        url = channel_url + "/videos"
    result = subprocess.run([
        "/root/.pyenv/versions/3.12.13/bin/yt-dlp", "--flat-playlist",
        "--print", "%(id)s",
        "--playlist-items", "1:15",
        "--no-warnings",
        url
    ], capture_output=True, text=True)
    return [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]

def get_video_meta(video_id):
    result = subprocess.run([
        "/root/.pyenv/versions/3.12.13/bin/yt-dlp",
        "--print", "%(upload_date)s|%(title)s",
        "--no-warnings", "--skip-download",
        f"https://www.youtube.com/watch?v={video_id}"
    ], capture_output=True, text=True)
    line = result.stdout.strip()
    if "|" not in line:
        return None, None
    date_str, title = line.split("|", 1)
    return date_str, title

def get_transcript(video_id):
    result = subprocess.run([
        "python3", "-c",
        f"import sys; sys.stdout.reconfigure(encoding='utf-8'); "
        f"from youtube_transcript_api import YouTubeTranscriptApi; "
        f"t = YouTubeTranscriptApi().fetch('{video_id}', languages=['de','en']); "
        f"print(' '.join([s.text for s in t.snippets]))"
    ], capture_output=True, text=True, timeout=30)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


def cleanup_db(con):
    """Bereinigt alte Einträge aus der DB."""
    # Transkripte älter als 7 Tage löschen (Text auf NULL setzen)
    result1 = con.execute("""
        UPDATE videos SET transcript=NULL
        WHERE transcript IS NOT NULL
        AND created_at < datetime('now', '-7 days')
    """)
    # Video-Einträge älter als 30 Tage komplett löschen
    result2 = con.execute("""
        DELETE FROM videos
        WHERE created_at < datetime('now', '-30 days')
    """)
    con.commit()
    print(f"  🧹 Cleanup: {result1.rowcount} Transkripte geleert, "
          f"{result2.rowcount} alte Einträge gelöscht.", flush=True)

def main():
    con = init_db()
    print("\n🧹 Starte Cleanup...", flush=True)
    cleanup_db(con)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=DAYS)).strftime("%Y%m%d")
    total_new = 0

    for channel_name, channel_url in CHANNELS:
        print(f"\n[{channel_name}] Scanning...", flush=True)
        video_ids = get_recent_video_ids(channel_url, DAYS)
        print(f"  → {len(video_ids)} candidate IDs", flush=True)

        for vid_id in video_ids:
            # Bereits in DB? Überspringen
            existing = con.execute(
                "SELECT video_id FROM videos WHERE video_id=?", (vid_id,)
            ).fetchone()
            if existing:
                print(f"  ⏭ {vid_id} bereits in DB", flush=True)
                continue

            date_str, title = get_video_meta(vid_id)
            if not date_str or date_str < cutoff:
                print(f"  ⏭ {vid_id} zu alt ({date_str})", flush=True)
                break  # Playlist ist chronologisch, ältere überspringen

            print(f"  📹 {title[:60]} ({date_str})", flush=True)
            print(f"     Transkript wird geholt...", flush=True)

            transcript = get_transcript(vid_id)
            if transcript:
                print(f"     ✓ {len(transcript)} Zeichen", flush=True)
            else:
                print(f"     ✗ Kein Transkript", flush=True)

            con.execute("""
                INSERT OR IGNORE INTO videos
                (video_id, channel, title, upload_date, transcript, status)
                VALUES (?,?,?,?,?,?)
            """, (vid_id, channel_name, title, date_str, transcript,
                  'pending' if transcript else 'no_transcript'))
            con.commit()
            total_new += 1

            if transcript:
                print(f"     💤 Warte {SLEEP_BETWEEN_VIDEOS}s...", flush=True)
                time.sleep(SLEEP_BETWEEN_VIDEOS)
            else:
                time.sleep(5)

    print(f"\n✅ Fertig. {total_new} neue Videos gespeichert.", flush=True)
    con.close()

if __name__ == "__main__":
    main()
