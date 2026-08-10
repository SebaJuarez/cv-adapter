"""Cross-Encoder Re-ranker para refinar el ranking híbrido.

Usa sentence-transformers CrossEncoder con device=cpu.
La query es SIEMPRE fija: extract_requirements_section(jd), acotada a 400 tokens
para dejar espacio al bullet (max 512 tokens para el par completo).

Si la query extraída sigue siendo muy larga, se trunca a 400 tokens por la derecha
antes de pasar al cross-encoder.
"""

import numpy as np


class CrossEncoderReranker:
    """Re-rankea bullets usando un cross-encoder local (CPU-only)."""

    def __init__(
        self,
        model_name: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
        device: str = "cpu",
    ):
        from sentence_transformers import CrossEncoder

        self.model = CrossEncoder(
            model_name,
            device=device,
            max_length=512,
        )
        self.model_name = model_name

    def rerank(
        self,
        query: str,
        bullet_docs: list[dict],
        top_k: int = 10,
    ) -> list[tuple[str, float]]:
        """Re-rankea bullets contra una query fija.

        Args:
            query: Texto de la query (ya acotada, ej. extract_requirements_section).
            bullet_docs: Lista de BulletDoc dicts con al menos "id" y "text".
            top_k: Cuántos resultados devolver.

        Returns:
            Lista de (bullet_id, score) ordenada por score descendente.
            Los scores están calibrados a [0, 1] vía sigmoid.
        """
        if not bullet_docs:
            return []

        pairs = [(query, b["text"]) for b in bullet_docs]
        raw_scores = self.model.predict(
            pairs,
            show_progress_bar=False,
            convert_to_numpy=True,
        )

        # Calibración: sigmoid para llevar scores crudos a rango acotado [0, 1]
        norm_scores = 1.0 / (1.0 + np.exp(-raw_scores))

        indexed = [(b["id"], float(norm_scores[i])) for i, b in enumerate(bullet_docs)]
        indexed.sort(key=lambda x: x[1], reverse=True)
        return indexed[:top_k]