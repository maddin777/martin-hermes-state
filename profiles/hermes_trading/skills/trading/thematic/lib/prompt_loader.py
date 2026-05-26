"""
Prompt Loader — Laedt versionierte Prompts aus dem prompts/-Verzeichnis
und fuehrt Template-Substitution durch.
"""
import os

_PROMPT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")


def load_prompt(name: str, **kwargs) -> str:
    """
    Laedt einen Prompt und ersetzt {PLACEHOLDER} mit kwargs.

    Args:
        name: Dateiname ohne Pfad (z.B. 'theme_discovery_v1.md')
        **kwargs: Key-Value-Paare fuer Template-Substitution

    Returns: Prompt-String mit eingesetzten Werten
    """
    path = os.path.join(_PROMPT_DIR, name)
    if not os.path.exists(path):
        return ""

    with open(path, "r", encoding="utf-8") as f:
        template = f.read()

    for key, value in kwargs.items():
        placeholder = "{" + key + "}"
        template = template.replace(placeholder, str(value))

    return template