"""Scripts padrão distribuídos com a imagem do Polaris.

O catálogo é fechado: o nome enviado por uma regra nunca vira caminho arbitrário de arquivo.
Uma instância carrega os bytes uma vez, para que a aprovação e a execução usem o mesmo conteúdo.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT_NAMES = (
    "disk_cleanup.sh",
    "kill_target_process.sh",
    "verify_disk.sh",
    "verify_cpu.sh",
    "verify_service.sh",
)


@dataclass(frozen=True, slots=True)
class Script:
    name: str
    content: bytes
    sha256: str


@dataclass(frozen=True, slots=True)
class ScriptCatalog:
    scripts: tuple[Script, ...]
    sha256: str

    def get(self, name: str) -> Script:
        for script in self.scripts:
            if script.name == name:
                return script
        raise ValueError(f"script não autorizado: {name}")


def load_catalog(directory: Path = SCRIPTS_DIR) -> ScriptCatalog:
    loaded: list[Script] = []
    for name in SCRIPT_NAMES:
        content = (directory / name).read_bytes()
        loaded.append(Script(name=name, content=content,
                             sha256=hashlib.sha256(content).hexdigest()))
    scripts = tuple(loaded)
    digest = hashlib.sha256()
    for script in scripts:
        digest.update(script.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(script.content)
        digest.update(b"\0")
    return ScriptCatalog(scripts=scripts, sha256=digest.hexdigest())
