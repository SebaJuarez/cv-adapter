"""Almacenamiento y persistencia de índices de retrieval.

Cada sección del CV (experience, projects, skills, education) tiene su propio
índice BM25, su propia matriz de embeddings y su propia metadata de bullets.
Los índices se persisten en disco y se invalidan cuando cambia el master_cv.yaml.
"""

import hashlib
import json
import pickle
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import numpy as np

INDEX_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "retrieval_index"


@dataclass
class BulletDoc:
    """Representa un bullet (highlight) del CV como documento indexable."""

    id: str  # "exp_0_bullet_2"
    text: str  # texto del bullet
    section: str  # "experience" | "projects" | "skills" | "education"
    entry_index: int  # índice de la entrada en la sección
    bullet_index: int  # índice del bullet dentro de la entrada
    entry_label: str  # nombre de empresa/proyecto/institución


class IndexStore:
    """Gestiona la persistencia de índices por sección.

    Estructura en disco:
        data/retrieval_index/
        ├── master_cv.hash
        ├── experience/
        │   ├── dense.npy
        │   ├── sparse.pkl
        │   └── bullets.json
        ├── projects/
        │   ├── dense.npy
        │   ├── sparse.pkl
        │   └── bullets.json
        └── ...
    """

    def __init__(self, index_dir: Path | None = None):
        self.index_dir = index_dir or INDEX_DIR
        self.index_dir.mkdir(parents=True, exist_ok=True)

    def _section_dir(self, section: str) -> Path:
        return self.index_dir / section

    def _hash_file(self) -> Path:
        return self.index_dir / "master_cv.hash"

    def get_stored_hash(self) -> str | None:
        path = self._hash_file()
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        return None

    def save_hash(self, yaml_content: str, params: dict | None = None) -> None:
        """Guarda la huella del índice: master + parámetros que cambian el
        corpus persistido (modelo denso, reranker, stemming). Sin los
        parámetros, cambiar dense_model en config con el master intacto
        cargaría embeddings viejos (dimensiones distintas = crash)."""
        self._hash_file().write_text(
            self.build_fingerprint(yaml_content, params), encoding="utf-8"
        )

    @staticmethod
    def build_fingerprint(yaml_content: str, params: dict | None = None) -> str:
        payload = {"master": yaml_content}
        if params:
            payload.update(params)
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def is_fresh(self, yaml_content: str, params: dict | None = None) -> bool:
        stored = self.get_stored_hash()
        if stored is None:
            return False
        return stored == self.build_fingerprint(yaml_content, params)

    def save_bullets(self, section: str, bullets: list[BulletDoc]) -> None:
        section_dir = self._section_dir(section)
        section_dir.mkdir(parents=True, exist_ok=True)
        data = [asdict(b) for b in bullets]
        (section_dir / "bullets.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def load_bullets(self, section: str) -> list[BulletDoc] | None:
        path = self._section_dir(section) / "bullets.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return [BulletDoc(**item) for item in data]

    def save_dense(self, section: str, embeddings: np.ndarray) -> None:
        section_dir = self._section_dir(section)
        section_dir.mkdir(parents=True, exist_ok=True)
        np.save(section_dir / "dense.npy", embeddings)

    def load_dense(self, section: str) -> np.ndarray | None:
        path = self._section_dir(section) / "dense.npy"
        if not path.exists():
            return None
        return np.load(path)

    def save_sparse(self, section: str, bm25_index) -> None:
        """Guarda el índice BM25Okapi (no el SparseIndex wrapper)."""
        section_dir = self._section_dir(section)
        section_dir.mkdir(parents=True, exist_ok=True)
        with open(section_dir / "sparse.pkl", "wb") as f:
            pickle.dump(bm25_index, f)

    def load_sparse(self, section: str):
        """Carga el índice BM25Okapi. Devuelve None si está corrupto o no existe."""
        path = self._section_dir(section) / "sparse.pkl"
        if not path.exists():
            return None
        try:
            with open(path, "rb") as f:
                obj = pickle.load(f)
            # Defensa: verificar que sea un BM25Okapi (tiene get_scores)
            if not hasattr(obj, "get_scores"):
                return None
            return obj
        except Exception:
            return None

    def clear(self) -> None:
        """Elimina todos los índices persistidos."""
        import shutil

        if self.index_dir.exists():
            shutil.rmtree(self.index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)