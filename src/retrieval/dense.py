"""Índice denso (embeddings) con Late Interaction (Max-Sim).

En lugar de hacer mean-pooling de los chunks del JD (que diluye el vector),
cada bullet se scorea contra TODOS los chunks del JD, y se queda con
la máxima similitud (Max-Sim / Late Interaction).

Ahora también devuelve best_chunk_indices para poder generar match reasons
que expliquen QUÉ parte del JD matcheó con cada bullet.
"""

import numpy as np


class DenseIndex:
    """Índice de embeddings para una sección del CV.

    Los bullets se normalizan al indexar. La query es una matriz de chunks
del JD (también normalizados). El score de cada bullet es el máximo
    producto punto contra todos los chunks (Max-Sim).
    """

    def __init__(self, model):
        """Args:
        model: instancia de SentenceTransformer ya cargada.
        """
        self.model = model
        self.bullet_ids: list[str] = []
        self.embeddings: np.ndarray | None = None  # (n_bullets, dim), L2-normalized

    def build(self, bullet_docs: list[dict]) -> None:
        """Construye el índice a partir de BulletDoc dicts."""
        self.bullet_ids = [b["id"] for b in bullet_docs]
        texts = [b["text"] for b in bullet_docs]
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