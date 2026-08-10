"""Índice denso (embeddings) con Late Interaction (Max-Sim).

En lugar de hacer mean-pooling de los chunks del JD (que diluye el vector),
cada bullet se scorea contra TODOS los chunks del JD, y se queda con
la máxima similitud (Max-Sim / Late Interaction).

Ahora también devuelve best_chunk_indices para poder generar match reasons
que expliquen QUÉ parte del JD matcheó con cada bullet.
"""

import numpy as np

# Prefijos requeridos por los modelos E5 (intfloat/multilingual-e5-*):
# la query lleva "query: " y los documentos "passage: ". Aplicarlos a
# modelos que no los esperan degrada el embedding, por eso se detecta
# por nombre de modelo antes de agregarlos.
_E5_QUERY_PREFIX = "query: "
_E5_PASSAGE_PREFIX = "passage: "


def _is_e5_model(model_name: str | None) -> bool:
    return bool(model_name) and "e5" in model_name.lower()


def prefixed_texts(texts: list[str], role: str, model_name: str | None) -> list[str]:
    """Antepone el prefijo E5 correspondiente (query:/passage:) si el modelo
    lo requiere. Con cualquier otro modelo devuelve los textos intactos."""
    if role not in ("query", "passage") or not _is_e5_model(model_name):
        return texts
    prefix = _E5_QUERY_PREFIX if role == "query" else _E5_PASSAGE_PREFIX
    return [prefix + t for t in texts]


class DenseIndex:
    """Índice de embeddings para una sección del CV.

    Los bullets se normalizan al indexar. La query es una matriz de chunks
    del JD (también normalizados). El score de cada bullet es el máximo
    producto punto contra todos los chunks (Max-Sim).
    """

    def __init__(self, model, model_name: str | None = None):
        """Args:
        model: instancia de SentenceTransformer ya cargada.
        model_name: nombre del modelo (para prefijos E5). Si es None se
            intenta derivar de model.model_card_data.
        """
        self.model = model
        self.model_name = model_name
        if self.model_name is None:
            try:
                self.model_name = model.model_card_data.get("model_name", "")
            except AttributeError:
                self.model_name = ""
        self.bullet_ids: list[str] = []
        self.embeddings: np.ndarray | None = None  # (n_bullets, dim), L2-normalized

    def build(self, bullet_docs: list[dict]) -> None:
        """Construye el índice a partir de BulletDoc dicts."""
        self.bullet_ids = [b["id"] for b in bullet_docs]
        texts = prefixed_texts([b["text"] for b in bullet_docs], "passage", self.model_name)
        # normalize_embeddings=True hace L2-normalization automática
        self.embeddings = self.model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

    def query(self, jd_chunk_matrix: np.ndarray, top_k: int = 50) -> tuple[list[str], dict[str, int]]:
        """Late Interaction (Max-Sim).

        Args:
            jd_chunk_matrix: (n_chunks, dim), L2-normalizada.
            top_k: cuántos bullet_ids devolver.

        Returns:
            - Lista de bullet_ids ordenados por score descendente.
            - Dict bullet_id -> índice del chunk del JD con máxima similitud.
        """
        if self.embeddings is None or len(self.bullet_ids) == 0:
            return [], {}
        sim_matrix = self.embeddings @ jd_chunk_matrix.T  # (n_bullets, n_chunks)
        scores = np.max(sim_matrix, axis=1)
        best_chunk_indices = np.argmax(sim_matrix, axis=1)
        n = len(scores)
        k = min(top_k, n)
        if k == 0:
            return [], {}
        top_indices = np.argpartition(scores, -k)[-k:]
        top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]

        ranked_ids = [self.bullet_ids[i] for i in top_indices]
        chunk_map = {self.bullet_ids[i]: int(best_chunk_indices[i]) for i in range(len(self.bullet_ids))}
        return ranked_ids, chunk_map