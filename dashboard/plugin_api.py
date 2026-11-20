"""Backend du widget « limites » : abonnements Claude, Codex, OpenCode Go et
dépense OpenRouter du jour.

Ce fichier ne contient plus la logique : il charge ``limits_reader.py`` **par
chemin**, en le rechargeant quand son mtime change. La passerelle importe un
module de plugin une seule fois au montage ; sans cet étage, toute correction du
lecteur exigeait un redémarrage de la passerelle pour devenir visible.

Routes :
    GET /data   -> instantané complet (cache 45 s côté lecteur)
"""

from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path
from types import ModuleType

from fastapi import APIRouter

_READER_PATH = Path(__file__).resolve().with_name("limits_reader.py")
_MODULE_NAME = "hermes_limites_reader"
_LOCK = threading.Lock()
_STATE: dict[str, object] = {"mtime": None, "module": None}

router = APIRouter()


def reader() -> ModuleType:
    """Le lecteur courant, rechargé dès que le fichier change sur le disque."""
    try:
        mtime = _READER_PATH.stat().st_mtime
    except OSError:
        mtime = None
    with _LOCK:
        module = _STATE.get("module")
        if isinstance(module, ModuleType) and _STATE.get("mtime") == mtime:
            return module
        spec = importlib.util.spec_from_file_location(_MODULE_NAME, _READER_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"lecteur introuvable : {_READER_PATH}")
        fresh = importlib.util.module_from_spec(spec)
        sys.modules[_MODULE_NAME] = fresh
        spec.loader.exec_module(fresh)
        _STATE["module"] = fresh
        _STATE["mtime"] = mtime
        return fresh


@router.get("/data")
def data(force: bool = False):
    return reader().snapshot(force=force)
