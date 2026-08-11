"""Importación de CVs viejos (F5): extracción de bullets desde texto libre,
YAML/JSON RenderCV o PDF, clustering automático por embeddings densos y
consolidación de clusters en achievements candidatos.

Invariante de la fase (doc §4.2.6): nada entra al master sin pasar por la
bandeja de revisión — este módulo solo produce CANDIDATOS y sesiones de
revisión guardables; la escritura al master la hace el frontend con el
POST /api/master-cv existente después de la confirmación humana.
"""

import base64
import json
import re
import uuid
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import yaml
from pypdf import PdfReader

from .llm_node import extract_achievement_facts
from .retrieval.dense import prefixed_texts

BULLET_MIN_LEN = 8
BULLET_MAX_LEN = 300
DEFAULT_CLUSTER_THRESHOLD = 0.78

_BULLET_PREFIX_RE = re.compile(r"^[\s\-•·*–—>]+")
# Una viñeta de verdad: espacios opcionales + un marcador no-espacio.
_BULLET_MARK_RE = re.compile(r"^\s*[-•·*–—>]")


# ---------------------------------------------------------------------------
# 1. Extracción de bullets crudos desde cada fuente

def _split_lines(text: str) -> List[str]:
    bullets: List[str] = []
    for line in (text or "").splitlines():
        s = _BULLET_PREFIX_RE.sub("", line).strip()
        s = " ".join(s.split())
        if not s:
            continue
        # Una línea sin viñeta es continuación del bullet anterior (muy
        # común en PDFs con texto justificado y en textos pegados) — solo
        # si es lo bastante larga; si no, es ruido (años, fechas sueltas).
        if not _BULLET_MARK_RE.match(line) and bullets and len(s) >= BULLET_MIN_LEN:
            bullets[-1] += " " + s
            continue
        if BULLET_MIN_LEN <= len(s) <= BULLET_MAX_LEN:
            bullets.append(s)
    return bullets


def _parse_text_doc(content: str) -> List[str]:
    return list(_split_lines(content))


def _parse_yaml_doc(content: str) -> List[str]:
    data = yaml.safe_load(content) or {}
    cv = data.get("cv", data) if isinstance(data, dict) else {}
    bullets: List[str] = []
    sections = cv.get("sections") or {}
    for entries in sections.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for h in entry.get("highlights") or []:
                if isinstance(h, str) and h.strip():
                    bullets.append(h.strip())
            for ach in entry.get("achievements") or []:
                if not isinstance(ach, dict):
                    continue
                for v in ach.get("variants") or []:
                    if isinstance(v, dict) and isinstance(v.get("text"), str) and v["text"].strip():
                        bullets.append(v["text"].strip())
    return bullets


def _parse_pdf_doc(content_b64: str) -> List[str]:
    raw = base64.b64decode(content_b64)
    reader = PdfReader(BytesIO(raw))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return list(_split_lines(text))


def parse_document(kind: str, content: str) -> List[str]:
    """Estructura el contenido de un CV en bullets candidatos.

    `kind` es "text", "yaml", "json" o "pdf" (para pdf, `content` es el
    archivo en base64). Un PDF o un texto suelto solo dan líneas; el texto
    plano pegado se comporta igual. El ruido del layout se filtra por
    longitud de línea y el resto se decide en la bandeja.
    """
    if kind == "pdf":
        return _parse_pdf_doc(content)
    if kind in ("yaml", "json"):
        return _parse_yaml_doc(content)
    return _parse_text_doc(content)


# ---------------------------------------------------------------------------
# 2. Clustering automático por embeddings densos (doc §4.2.3)

def _dense_similarity_matrix(texts: List[str], model, model_name: str) -> np.ndarray:
    prefixed = prefixed_texts(texts, "passage", model_name)
    embeddings = model.encode(prefixed, convert_to_numpy=True, normalize_embeddings=True)
    return embeddings @ embeddings.T


def cluster_bullets(
    texts: List[str],
    similarity_fn: Optional[Callable[[List[str]], np.ndarray]] = None,
    threshold: float = DEFAULT_CLUSTER_THRESHOLD,
) -> List[List[int]]:
    """Agrupa índices de bullets que probablemente son el mismo logro
    redactado distinto (Max-Sim mutuo: un par se une solo si cada uno es
    el vecino más similar del otro, y con similitud >= `threshold`).

    El umbral absoluto no alcanza solo: con embeddings densos multilingües
    los bullets de un mismo CV (mismo estilo, mismo dominio) suelen tener
    similitud base alta (0.87-0.91) aunque sean logros distintos. Exigir
    que el par sea el máximo mutuo de ambas filas evita que un bullet
    "embudo" encadene todo el documento en un solo cluster.

    Los que no se agrupan con nadie quedan como clusters de un elemento
    (huérfanos: aparecen una sola vez en un solo CV). `similarity_fn` es
    inyectable para tests; por defecto usa el modelo denso del config.
    """
    n = len(texts)
    if n == 0:
        return []
    if similarity_fn is None:
        similarity_fn = _default_similarity
    sim = similarity_fn(texts)

    row_max = [0.0] * n
    for i in range(n):
        for j in range(n):
            if j != i and sim[i][j] > row_max[i]:
                row_max[i] = sim[i][j]

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            mutual_max = sim[i][j] >= row_max[i] - 1e-9 and sim[i][j] >= row_max[j] - 1e-9
            if mutual_max and sim[i][j] >= threshold:
                union(i, j)

    groups: Dict[int, List[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return sorted(groups.values(), key=len, reverse=True)


def _default_similarity(texts: List[str]) -> np.ndarray:
    from sentence_transformers import SentenceTransformer

    from .config import load_config

    config = load_config()
    model_name = config.get("dense_model", "intfloat/multilingual-e5-small")
    model = SentenceTransformer(model_name, device="cpu")
    return _dense_similarity_matrix(texts, model, model_name)


# ---------------------------------------------------------------------------
# 3. Consolidación del cluster en un achievement candidato (doc §4.2.4)

def consolidate_cluster_facts(texts: List[str], config: Dict[str, Any]) -> Dict[str, Any]:
    """Propone el `facts` de un cluster confirmado como "es el mismo logro":

    extrae los hechos de cada redacción (defensivo: si el LLM falla para
    una, esa redacción no aporta nada) y une tools y outcomes únicos. La
    acción/alcance vienen de la redacción más larga, que suele ser la más
    completa. Nunca inventa datos: solo lo que cada redacción aporta.
    """
    facts: Dict[str, Any] = {"action": "", "tools": [], "scope": "", "outcomes": []}
    seen_tools = set()
    seen_outcomes = set()
    for text in sorted(texts, key=len, reverse=True):
        f = extract_achievement_facts(text, config)
        if not facts["action"] and f.get("action"):
            facts["action"] = f["action"]
        if not facts["scope"] and f.get("scope"):
            facts["scope"] = f["scope"]
        for t in f.get("tools", []):
            if t not in seen_tools:
                seen_tools.add(t)
                facts["tools"].append(t)
        for o in f.get("outcomes", []):
            key = (o.get("metric", ""), o.get("value", ""))
            if key not in seen_outcomes:
                seen_outcomes.add(key)
                facts["outcomes"].append(o)
    if not facts["action"]:
        facts["action"] = texts[0]
    return facts


def build_achievement_candidate(texts: List[str], facts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Un achievement candidato con cada redacción como variante imported.

    El usuario lo ve y confirma en la bandeja; recién entonces el
    frontend lo escribe al master. `facts` consolidado viene de
    consolidate_cluster_facts (o vacío si el LLM no está disponible).
    """
    return {
        "id": f"ach_imp_{uuid.uuid4().hex[:10]}",
        "facts": facts or {"action": "", "tools": [], "scope": "", "outcomes": []},
        "variants": [
            {
                "id": f"var_imp_{uuid.uuid4().hex[:10]}",
                "text": t,
                "angle": "",
                "status": "approved",
                "source": "imported",
                "used_count": 0,
                "created_at": str(date.today()),
            }
            for t in texts
        ],
    }


# ---------------------------------------------------------------------------
# 4. Sesión de revisión guardable (doc §6.3: "guardar a medias y volver")

_RESOLUTION_STATUSES = ("pending", "awaiting", "done")


class ImportSession:
    """Una importación en revisión: bullets crudos + clusters propuestos +
    resoluciones del usuario. Se persiste en JSON para poder retomarla."""

    def __init__(self, session_id: str, bullets: List[Dict[str, Any]],
                 clusters: List[Dict[str, Any]], orphan_ids: List[int]):
        self.id = session_id
        self.bullets = bullets
        self.clusters = clusters
        self.orphan_ids = orphan_ids
        # cluster_id -> {"status": pending|awaiting|done, "candidates": [...]}
        self.resolutions: Dict[str, Dict[str, Any]] = {}
        for c in clusters:
            self.resolutions[c["id"]] = {"status": "pending", "candidates": []}
        self.orphans_done = False

    # -- consultas --------------------------------------------------------

    def total_groups(self) -> int:
        return len(self.clusters) + (0 if self.orphans_done else 1)

    def reviewed_groups(self) -> int:
        done = sum(1 for r in self.resolutions.values() if r["status"] == "done")
        return done + (1 if self.orphans_done else 0)

    def cluster(self, cluster_id: str) -> Optional[Dict[str, Any]]:
        return next((c for c in self.clusters if c["id"] == cluster_id), None)

    def cluster_texts(self, cluster_id: str) -> List[str]:
        c = self.cluster(cluster_id)
        if not c:
            return []
        return [self.bullets[i]["text"] for i in c["bullet_ids"]]

    # -- mutaciones -------------------------------------------------------

    def schedule_candidates(self, cluster_id: str, candidates: List[Dict[str, Any]]) -> None:
        """El cluster se resolvió y hay candidatos esperando confirmación
        del usuario (estado "awaiting" para retomar si se va a mitad)."""
        rec = self.resolutions.get(cluster_id)
        if rec:
            rec["status"] = "awaiting"
            rec["candidates"] = candidates

    def mark_done(self, cluster_id: str) -> None:
        rec = self.resolutions.get(cluster_id)
        if rec:
            rec["status"] = "done"

    def pending_cluster_ids(self) -> List[str]:
        return [c["id"] for c in self.clusters if self.resolutions.get(c["id"], {}).get("status") == "pending"]

    # -- serialización ----------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "bullets": self.bullets,
            "clusters": self.clusters,
            "orphan_ids": self.orphan_ids,
            "orphans_done": self.orphans_done,
            "resolutions": self.resolutions,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImportSession":
        s = cls(data["id"], data["bullets"], data["clusters"], data["orphan_ids"])
        s.orphans_done = bool(data.get("orphans_done"))
        s.resolutions = data.get("resolutions") or {}
        return s


def new_session_id() -> str:
    return f"imp_{uuid.uuid4().hex[:10]}"


def save_session(session: ImportSession, sessions_dir: Path) -> Path:
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = sessions_dir / f"{session.id}.json"
    path.write_text(json.dumps(session.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_session(session_id: str, sessions_dir: Path) -> Optional[ImportSession]:
    path = sessions_dir / f"{session_id}.json"
    if not path.exists():
        return None
    try:
        return ImportSession.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return None