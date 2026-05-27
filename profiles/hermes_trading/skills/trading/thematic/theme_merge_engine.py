"""
Theme Merge Engine — Embedding-basiertes Deduplizieren von Themen.
3-Stufen: Auto-Merge (>=0.88), Review-Queue (0.75-0.88), Neues Theme (<0.75)
"""
import json
import os
import sqlite3
from datetime import date
from thematic.lib.embedding_client import embed_theme, cosine_similarity

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "trading.db"
)


def _load_active_embeddings(con):
    """Laedt Embeddings aller aktiven/decelerating-Themen."""
    rows = con.execute("""
        SELECT id, name, description, embedding_vector
        FROM theme_definitions
        WHERE status IN ('active', 'decelerating')
    """).fetchall()
    return rows


def auto_merge_theme(con, new_data: dict, existing_id: int):
    """Auto-Update eines bestehenden Themes."""
    existing = con.execute(
        "SELECT * FROM theme_definitions WHERE id = ?", (existing_id,)
    ).fetchone()
    if not existing:
        return

    old_sources = json.loads(existing["sources_json"] or "[]")
    new_sources_raw = new_data.get("key_sources", "[]")
    try:
        new_srcs = json.loads(new_sources_raw) if isinstance(new_sources_raw, str) else new_sources_raw
    except (json.JSONDecodeError, TypeError):
        new_srcs = []
    import json
    try:
        old_list = json.loads(old_sources) if isinstance(old_sources, str) else (old_sources or [])
    except Exception:
        old_list = []
    new_list = new_srcs if isinstance(new_srcs, list) else []
    merged_sources = list(set([s for s in old_list + new_list if isinstance(s, str)]))

    # Gewichtetes Mittel Underreported-Score
    old_score = float(existing["underreported_score"] or 0.5)
    new_score = float(new_data.get("underreported_score", 0.5))
    blended_score = 0.7 * old_score + 0.3 * new_score

    today = date.today().isoformat()

    con.execute("""
        UPDATE theme_definitions SET
            last_seen = ?,
            coverage_count = coverage_count + 1,
            sources_json = ?,
            momentum = ?,
            underreported_score = ?,
            pm_confirmation_status = ?,
            pm_confirmation_score = ?
        WHERE id = ?
    """, (
        today,
        json.dumps(merged_sources),
        new_data.get("momentum", "steady"),
        round(blended_score, 4),
        new_data.get("pm_signal", "no_data"),
        0.0,
        existing_id,
    ))
    con.commit()
    print(f"  🔄 Auto-Merged: '{new_data.get('name')}' -> existing ID {existing_id}", flush=True)


def queue_for_review(con, new_data: dict, candidate_id: int, similarity: float):
    """Stellt ein Theme in die Review-Queue."""
    con.execute("""
        INSERT INTO theme_merge_queue
        (new_theme_data, candidate_existing_id, similarity_score, status)
        VALUES (?, ?, ?, 'pending')
    """, (
        json.dumps(new_data, ensure_ascii=False),
        candidate_id,
        round(similarity, 4),
    ))
    con.commit()
    print(f"  📋 Review-Queue: '{new_data.get('name')}' ~ ID {candidate_id} "
          f"(Sim={similarity:.3f})", flush=True)


def insert_new_theme(con, new_data: dict) -> int:
    """Fuegt ein komplett neues Theme ein."""
    today = date.today().isoformat()
    name = new_data.get("name", "")
    description = new_data.get("description", "")

    # Embedding berechnen
    embedding = embed_theme(name, description)
    embedding_json = json.dumps(embedding)

    con.execute("""
        INSERT INTO theme_definitions
        (name, category, description, first_detected, last_seen,
         status, momentum, underreported_score, coverage_count,
         sources_json, embedding_vector,
         pm_confirmation_status, pm_confirmation_score)
        VALUES (?, ?, ?, ?, ?, 'active', ?, ?, 1, ?, ?, ?, ?)
    """, (
        name,
        new_data.get("category", "sector"),
        description,
        today,
        today,
        new_data.get("momentum", "steady"),
        float(new_data.get("underreported_score", 0.5)),
        json.dumps(new_data.get("key_sources", [])),
        embedding_json,
        new_data.get("pm_signal", "no_data"),
        0.0,
    ))
    new_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    con.commit()
    print(f"  ✨ Neues Theme: '{name}' (ID {new_id})", flush=True)
    return new_id


def check_and_merge(new_data: dict, con) -> int:
    """
    Haupt-Funktion: Prueft ob ein Thema neu ist, gemerged oder in Review-Queue kommt.

    Returns: existing theme_id (>0 = existing/merged), 0 = new theme
    """
    name = new_data.get("name", "")
    description = new_data.get("description", "")

    if not name or not description:
        return 0

    embedding = embed_theme(name, description)
    active = _load_active_embeddings(con)

    if not active:
        insert_new_theme(con, new_data)
        return 0

    best_sim = 0.0
    best_id = None

    for row in active:
        stored_vec = row["embedding_vector"]
        if not stored_vec:
            continue
        try:
            vec = json.loads(stored_vec) if isinstance(stored_vec, str) else stored_vec
            sim = cosine_similarity(embedding, vec)
            if sim > best_sim:
                best_sim = sim
                best_id = row["id"]
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

    config_path = os.path.join(
        os.path.dirname(__file__), "config", "thematic_config.json"
    )
    with open(config_path) as f:
        cfg = json.load(f)
    thresholds = cfg.get("thresholds", {})
    auto_thresh = thresholds.get("theme_merge_auto_similarity", 0.88)
    review_thresh = thresholds.get("theme_merge_review_similarity", 0.75)

    if best_id and best_sim >= auto_thresh:
        auto_merge_theme(con, new_data, best_id)
        return best_id
    elif best_id and best_sim >= review_thresh:
        queue_for_review(con, new_data, best_id, best_sim)
        return best_id
    else:
        insert_new_theme(con, new_data)
        return 0