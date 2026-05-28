"""
Embedding Client — Cosine-Similarity fuer Theme-Merge.
Primaer: OpenAI text-embedding-3-small via OpenRouter
Fallback: sentence-transformers (lokal)
Kein separater OPENAI_API_KEY noetig — alles ueber OPENROUTER_API_KEY.
"""
import os
import sys
sys.path.insert(0, "/root/.hermes/profiles/hermes_trading/skills/trading")
import env_loader  # noqa: F401  (side-effect: laedt .env)
import json
import requests
import numpy as np

OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
EMBED_MODEL = "openai/text-embedding-3-small"

_fallback_model = None


def _get_fallback_model():
    global _fallback_model
    if _fallback_model is not None:
        return _fallback_model
    try:
        from sentence_transformers import SentenceTransformer
        _fallback_model = SentenceTransformer("all-MiniLM-L6-v2")
    except Exception:
        _fallback_model = False
    return _fallback_model


def embed(text: str) -> list:
    """
    Berechnet Embedding-Vektor fuer einen Text.
    Versucht zuerst OpenRouter (text-embedding-3-small), dann lokales Modell.
    """
    if OPENROUTER_KEY:
        return _embed_openrouter(text)

    model = _get_fallback_model()
    if model:
        return _embed_local(text, model)

    return _embed_token_overlap(text)


def _embed_openrouter(text: str) -> list:
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/embeddings",
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": EMBED_MODEL,
                "input": text[:8000],
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
    except Exception as e:
        print(f"[Embedding] OpenRouter-Fehler: {e}")
        model = _get_fallback_model()
        if model:
            return _embed_local(text, model)
        return _embed_token_overlap(text)


def _embed_local(text: str, model) -> list:
    try:
        return model.encode(text[:8000]).tolist()
    except Exception:
        return _embed_token_overlap(text)


def _embed_token_overlap(text: str, dims: int = 384) -> list:
    """Mini-Embedding aus Token-Hashes (Fallback)."""
    import hashlib
    tokens = text.lower().split()
    vec = [0.0] * dims
    for token in tokens:
        h = hashlib.md5(token.encode()).digest()
        for i in range(min(len(h), dims)):
            vec[i] += (h[i] - 128) / 128
    norm = max(np.linalg.norm(vec), 1e-8)
    return (np.array(vec) / norm).tolist()


def cosine_similarity(vec_a: list, vec_b: list) -> float:
    """Berechnet Cosine-Similarity zwischen zwei Embedding-Vektoren."""
    a = np.array(vec_a)
    b = np.array(vec_b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


def embed_theme(name: str, description: str) -> list:
    """Erstellt Embedding aus Theme-Name + Beschreibung."""
    return embed(f"{name}: {description}")