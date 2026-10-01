"""N7: Rauchtest ueber alle Module: jede .py-Datei kompiliert, und jedes Modul mit __main__-Guard und harmlosem Modul-Level
importiert ohne Fehler. Faengt Syntax-/Namensfehler beim Laden frueh (z. B. ein Tippfehler nach einem Patch).
Ausgeschlossen: tests/, venv/. Module mit Modul-Level-Aufrufen (ausser sys.path/warnings/logging/load_dotenv) werden
nicht importiert, damit der Test keine Seiteneffekte ausloest."""
import ast
import glob
import importlib.util
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
ALLOWED_CALLS = ("sys.path.insert", "sys.path.append", "warnings.filterwarnings", "logging.basicConfig",
                 "load_dotenv", "warnings.simplefilter")
# Module, die in Tests bewusst fehlen duerfen (nur im Cron-Interpreter installiert, siehe N8)
OPTIONAL_THIRD_PARTY = {"feedparser"}
# Bekannte Defekte: Modul -> Grund (Verweis auf Befund-ID). Leer = alles importiert.
BEKANNT_DEFEKT = {}


def _files():
    pats = ["*.py", "scripts/*.py", "thematic/*.py", "thematic/lib/*.py", "backtesting/*.py", "roles/*.py"]
    out = []
    for p in pats:
        out += glob.glob(os.path.join(ROOT, p))
    return sorted(f for f in out if "/tests/" not in f.replace("\\", "/") and "venv" not in f)


def _importable(path):
    src = open(path, encoding="utf-8").read()
    if not ("__name__" in src and "__main__" in src):
        return False
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Expr) and not isinstance(node.value, ast.Constant):
            call = ast.unparse(node.value.func) if isinstance(node.value, ast.Call) else ""
            if not call.startswith(ALLOWED_CALLS):
                return False
        if isinstance(node, (ast.For, ast.While, ast.Delete)):
            return False
    return True


FILES = _files()
IDS = [os.path.relpath(f, ROOT) for f in FILES]


def test_the_project_has_a_plausible_number_of_modules():
    assert len(FILES) > 60


@pytest.mark.parametrize("path", FILES, ids=IDS)
def test_module_compiles(path):
    compile(ast.parse(open(path, encoding="utf-8").read(), path), path, "exec")


@pytest.mark.parametrize("path", [f for f in FILES if _importable(f)], ids=[i for f, i in zip(FILES, IDS) if _importable(f)])
def test_module_imports(path):
    rel = os.path.relpath(path, ROOT)
    if rel in BEKANNT_DEFEKT:
        pytest.skip(BEKANNT_DEFEKT[rel])
    spec = importlib.util.spec_from_file_location("smoke_" + rel.replace("/", "_").replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ModuleNotFoundError as e:
        if e.name in OPTIONAL_THIRD_PARTY:
            pytest.skip(f"{e.name} nur im Cron-Interpreter installiert (N8)")
        raise
