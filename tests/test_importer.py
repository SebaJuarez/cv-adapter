"""Tests de la importación de CVs: parseo de fuentes, clustering,
consolidación y la sesión de revisión con su API.

Invariante: el router nunca escribe el master — solo arma
candidatos y sesiones; la confirmación en el master es POST
/api/master-cv (ya cubierto en test_master_cv_api.py).
"""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    master_path = tmp_path / "master_cv.yaml"
    runs_path = tmp_path / "run_history.json"
    sessions_dir = tmp_path / "import_sessions"
    monkeypatch.setattr("api.deps.MASTER_CV_PATH", master_path)
    monkeypatch.setattr("api.routers.master_cv.MASTER_CV_PATH", master_path)
    monkeypatch.setattr("api.routers.master_cv.RUNS_PATH", runs_path)
    monkeypatch.setattr("api.routers.history.RUNS_PATH", runs_path)
    monkeypatch.setattr("api.deps.RUNS_PATH", runs_path)
    monkeypatch.setattr("api.routers.generate.RUNS_PATH", runs_path)
    monkeypatch.setattr("api.deps.IMPORT_SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr("api.routers.imports.IMPORT_SESSIONS_DIR", sessions_dir)
    return TestClient(app)


def _no_net_similarity(monkeypatch):
    """Desactiva el clustering por embeddings reales en el router: el
    matching exacto agrupa solo bullets idénticos."""
    import src.importer as importer

    def fake_similarity(texts):
        n = len(texts)
        m = np.eye(n)
        for i in range(n):
            for j in range(n):
                m[i][j] = 1.0 if texts[i] == texts[j] else 0.0
        return m

    monkeypatch.setattr(importer, "_default_similarity", fake_similarity)
    return importer.cluster_bullets


# ---------------------------------------------------------------------------
# parse_document

def test_parse_text_limpia_vinetas_y_filtra_lineas_cortas():
    from src.importer import parse_document

    doc = """
    - Desarrollé el backend de una app de delivery en Python
      con PostgreSQL y Redis.
    • Automatización de reportes con scripts de Python.
    2021
    """
    bullets = parse_document("text", doc)
    assert bullets == [
        "Desarrollé el backend de una app de delivery en Python con PostgreSQL y Redis.",
        "Automatización de reportes con scripts de Python.",
    ]


def test_parse_text_limita_concat_de_linea_sin_vineta():
    from src.importer import parse_document

    # Un PDF mal extraído puede venir como una sola línea gigante (o una
    # sección entera sin viñetas): jamás se deja crecer un bullet pasado
    # BULLET_MAX_LEN concatenando continuaciones.
    largo = "palabra " * 200
    doc = f"Sebastián Juárez\nLos Cardales, Buenos Aires\n{largo.strip()}\nDesarrollé el backend en Python."
    bullets = parse_document("text", doc)
    assert all(len(b) <= 300 for b in bullets)
    assert any("Desarrollé el backend en Python." in b for b in bullets)


def test_parse_text_normaliza_vineta_corrupta_del_pdf():
    from src.importer import parse_document

    # pypdf extrae la viñeta bullet de ciertos PDFs como \x88 (cp1252 mal
    # mapeado): debe tratarse como viñeta nueva, no como continuación.
    doc = "Encabezado\n\x88 Desarrollé el backend con Java.\n\x88 Implementé tests con pytest."
    bullets = parse_document("text", doc)
    assert bullets == [
        "Encabezado",
        "Desarrollé el backend con Java.",
        "Implementé tests con pytest.",
    ]


def test_parse_yaml_extrae_highlights_y_variantes():
    from src.importer import parse_document

    doc = """
cv:
  sections:
    experience:
      - company: Empresa A
        highlights:
          - Hice el backend en Java.
    projects:
      - name: Proyecto
        achievements:
          - variants:
              - text: "Diseñé el sistema completo."
    skills:
      - label: Lenguajes
        details: Java, Python
"""
    bullets = parse_document("yaml", doc)
    assert bullets == ["Hice el backend en Java.", "Diseñé el sistema completo."]


def _minimal_pdf(text: str) -> bytes:
    """Arma un PDF válido con una línea de texto (para testear pypdf)."""
    from pypdf import PdfReader

    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode()
    )
    pdf = PdfReader(__import__("io").BytesIO(out))
    assert len(pdf.pages) == 1  # el fixture es un PDF válido
    return out


def test_parse_pdf_extrae_texto():
    import base64

    from src.importer import parse_document

    pdf_bytes = _minimal_pdf("Trabaje en una red corporativa con MPLS.")
    bullets = parse_document("pdf", base64.b64encode(pdf_bytes).decode("ascii"))
    assert bullets == ["Trabaje en una red corporativa con MPLS."]


# ---------------------------------------------------------------------------
# cluster_bullets

def test_clustering_max_sim_mutuо_evita_embudo():
    from src.importer import cluster_bullets

    # Un bullet "embudo" (3) es similar a todos pero no es el máximo de
    # NINGUNA fila: no puede unir grupos de logs distintos en un cluster.
    # Sim del scoring real con e5-small: duplicados ~0.95+, no-duplicados 0.88-0.91.
    m = np.array([
        [1.0, 0.88, 0.89, 0.90, 0.98, 0.89],
        [0.88, 1.0, 0.87, 0.91, 0.89, 0.95],
        [0.89, 0.87, 1.0, 0.90, 0.88, 0.89],
        [0.90, 0.91, 0.90, 1.0, 0.90, 0.90],
        [0.98, 0.89, 0.88, 0.90, 1.0, 0.89],
        [0.89, 0.95, 0.89, 0.90, 0.89, 1.0],
    ])
    groups = cluster_bullets(
        ["A", "B", "C", "D", "A2", "B2"],
        similarity_fn=lambda t: m,
        threshold=0.9,
    )
    assert sorted(map(sorted, groups)) == [[0, 4], [1, 5], [2], [3]]


def test_clustering_agrupa_similares_y_deja_huerfanos():
    from src.importer import cluster_bullets

    texts = [
        "Desarrollé el backend de la app de delivery en Python.",
        "Backend de la app de delivery hecho en Python.",
        "Desarrollé el backend en Python para la app de delivery.",
        "Diseñé la arquitectura de red de la aerolínea.",
        "Hice el relevamiento de requisitos del proyecto.",
    ]

    def fake_sim(t):
        n = len(t)
        m = np.zeros((n, n))
        similar = {0, 1, 2}
        for i in range(n):
            for j in range(n):
                m[i][j] = 0.9 if (i in similar and j in similar) else 0.0
        np.fill_diagonal(m, 1.0)
        return m

    groups = cluster_bullets(texts, similarity_fn=fake_sim, threshold=0.8)
    assert sorted(map(sorted, groups)) == [[0, 1, 2], [3], [4]]


def test_clustering_transitivo_con_empates_de_maximo():
    from src.importer import cluster_bullets

    # A~B y B~C con B como máximo empate de ambos: las tres se unen
    # (la transitividad del union sobrevive al criterio de máximo mutuo).
    def sim(t):
        m = np.eye(3)
        m[0][1] = m[1][0] = 0.9
        m[1][2] = m[2][1] = 0.9
        return m

    groups = cluster_bullets(["a a a", "a a b", "b b b"], similarity_fn=sim, threshold=0.8)
    assert len(groups) == 1 and len(groups[0]) == 3


# ---------------------------------------------------------------------------
# consolidate_cluster_facts

def test_consolidacion_une_tools_y_outcomes(monkeypatch, config):
    from src.importer import consolidate_cluster_facts

    def llm_ok(system_prompt, user_prompt, schema, cfg):
        bullet = user_prompt.split("### bullet ###\n")[1].split("\n\n")[0]
        if "Python" in bullet:
            return {"action": "Desarrollé el backend en Python", "tools": ["Python"],
                    "scope": "app", "outcomes": [{"metric": "tiempo", "value": "50%"}]}
        return {"action": "", "tools": ["Redis"], "scope": "",
                "outcomes": [{"metric": "tiempo", "value": "50%"}, {"metric": "costo", "value": "-30%"}]}

    monkeypatch.setattr("src.llm_node._call_llm", llm_ok)
    facts = consolidate_cluster_facts([
        "Desarrollé el backend en Python reduciendo el tiempo un 50%",
        "Optimicé con Redis el costo un -30%",
    ], config)
    assert facts["action"] == "Desarrollé el backend en Python"
    assert facts["tools"] == ["Python", "Redis"]
    assert facts["outcomes"] == [
        {"metric": "tiempo", "value": "50%"},
        {"metric": "costo", "value": "-30%"},
    ]  # dedupe por (metric, value)


def test_consolidacion_con_llm_roto_cae_al_primer_texto(monkeypatch, config):
    from src.importer import consolidate_cluster_facts

    def llm_roto(*args, **kwargs):
        raise RuntimeError("proveedor caído")

    monkeypatch.setattr("src.llm_node._call_llm", llm_roto)
    facts = consolidate_cluster_facts(["Hice mantenimiento de servidores."], config)
    assert facts["action"] == "Hice mantenimiento de servidores."
    assert facts["tools"] == []


def test_candidate_imported_tiene_todas_las_variantes():
    from src.importer import build_achievement_candidate

    candidate = build_achievement_candidate(["A", "B"], {"action": "X", "tools": [], "scope": "", "outcomes": []})
    assert candidate["id"].startswith("ach_imp_")
    assert [v["text"] for v in candidate["variants"]] == ["A", "B"]
    assert all(v["source"] == "imported" for v in candidate["variants"])
    assert all(v["status"] == "approved" for v in candidate["variants"])


# ---------------------------------------------------------------------------
# Sesión

def test_session_roundtrip_y_progreso(tmp_path):
    from src.importer import ImportSession, build_achievement_candidate, load_session, save_session

    bullets = [{"text": f"Bullet {i}", "file": "cv.pdf"} for i in range(4)]
    clusters = [{"id": "cl_1", "bullet_ids": [0, 2], "file": "cv.pdf"}]
    s = ImportSession("imp_test", bullets, clusters, orphan_ids=[1, 3])
    assert s.total_groups() == 2
    assert s.reviewed_groups() == 0
    s.schedule_candidates("cl_1", [build_achievement_candidate(["Bullet 0", "Bullet 2"], {})])
    assert s.reviewed_groups() == 0  # awaiting no cuenta como revisado
    s.mark_done("cl_1")
    assert s.reviewed_groups() == 1
    s.orphans_done = True
    assert s.reviewed_groups() == 2

    save_session(s, tmp_path)
    loaded = load_session("imp_test", tmp_path)
    assert loaded is not None
    assert loaded.bullets == bullets
    assert loaded.resolutions["cl_1"]["status"] == "done"


# ---------------------------------------------------------------------------
# API

def test_clusterize_crea_sesion(client, monkeypatch):
    _no_net_similarity(monkeypatch)
    resp = client.post("/api/imports/clusterize", json={
        "files": [
            {"name": "cv1.txt", "kind": "text",
             "content": "- Desarrollé el backend en Python.\n- Diseñé la red."},
            {"name": "cv2.txt", "kind": "text",
             "content": "- Desarrollé el backend en Python."},
        ],
    })
    assert resp.status_code == 200
    session = resp.json()["session"]
    assert len(session["bullets"]) == 3
    assert len(session["clusters"]) == 1  # el duplicado exacto agrupa
    assert session["clusters"][0]["bullet_ids"] == [0, 2]
    assert session["orphan_ids"] == [1]


def test_clusterize_rechaza_archivos_invalidos(client, monkeypatch):
    _no_net_similarity(monkeypatch)
    resp = client.post("/api/imports/clusterize", json={
        "files": [{"name": "x.doc", "kind": "doc", "content": "hola"}],
    })
    assert resp.status_code == 422


def test_resolve_merge_genera_candidato_con_facts_consolidados(client, monkeypatch, config):
    _no_net_similarity(monkeypatch)

    def llm_ok(system_prompt, user_prompt, schema, cfg):
        return {"action": "Desarrollé el backend en Python", "tools": ["Python"],
                "scope": "", "outcomes": []}

    monkeypatch.setattr("src.llm_node._call_llm", llm_ok)
    resp = client.post("/api/imports/clusterize", json={
        "files": [{"name": "cv.txt", "kind": "text",
                   "content": "- Desarrollé el backend en Python.\n- Desarrollé el backend en Python."}],
    })
    session = resp.json()["session"]
    cluster_id = session["clusters"][0]["id"]

    resp = client.post(f"/api/imports/session/{session['id']}/resolve",
                       json={"cluster_id": cluster_id, "action": "merge"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["candidates"]) == 1
    cand = body["candidates"][0]
    assert len(cand["variants"]) == 2
    assert cand["facts"]["tools"] == ["Python"]
    assert body["session"]["resolutions"][cluster_id]["status"] == "awaiting"

    # confirmar cierra el cluster
    resp = client.post(f"/api/imports/session/{session['id']}/confirm",
                       json={"cluster_id": cluster_id})
    assert resp.status_code == 200
    assert resp.json()["session"]["resolutions"][cluster_id]["status"] == "done"


def test_resolve_discard_sin_candidatos(client, monkeypatch):
    _no_net_similarity(monkeypatch)
    resp = client.post("/api/imports/clusterize", json={
        "files": [{"name": "cv.txt", "kind": "text",
                   "content": "- Desarrollé el backend en Python.\n- Desarrollé el backend en Python."}],
    })
    session = resp.json()["session"]
    cluster_id = session["clusters"][0]["id"]
    resp = client.post(f"/api/imports/session/{session['id']}/resolve",
                       json={"cluster_id": cluster_id, "action": "discard"})
    assert resp.status_code == 200
    assert resp.json()["candidates"] == []


def test_resolve_split_genera_un_candidato_por_redaccion(client, monkeypatch, config):
    _no_net_similarity(monkeypatch)

    def llm_ok(system_prompt, user_prompt, schema, cfg):
        return {"action": "X", "tools": [], "scope": "", "outcomes": []}

    monkeypatch.setattr("src.llm_node._call_llm", llm_ok)
    resp = client.post("/api/imports/clusterize", json={
        "files": [{"name": "cv.txt", "kind": "text",
                   "content": "- Desarrollé el backend en Python.\n- Desarrollé el backend en Python."}],
    })
    session = resp.json()["session"]
    cluster_id = session["clusters"][0]["id"]
    resp = client.post(f"/api/imports/session/{session['id']}/resolve",
                       json={"cluster_id": cluster_id, "action": "split"})
    assert resp.status_code == 200
    assert len(resp.json()["candidates"]) == 2
    assert all(len(c["variants"]) == 1 for c in resp.json()["candidates"])


def test_orphans_se_aceptan_con_action_del_texto(client, monkeypatch):
    _no_net_similarity(monkeypatch)
    resp = client.post("/api/imports/clusterize", json={
        "files": [{"name": "cv.txt", "kind": "text", "content": "- Diseñé la red."}],
    })
    session = resp.json()["session"]
    assert session["orphan_ids"] == [0]
    resp = client.post(f"/api/imports/session/{session['id']}/orphans", json={"accept": True})
    body = resp.json()
    assert len(body["candidates"]) == 1
    assert body["candidates"][0]["facts"]["action"] == "Diseñé la red."
    assert body["session"]["orphans_done"] is True


def test_orphans_se_pueden_descartar_sin_candidatos(client, monkeypatch):
    _no_net_similarity(monkeypatch)
    resp = client.post("/api/imports/clusterize", json={
        "files": [{"name": "cv.txt", "kind": "text", "content": "- Diseñé la red."}],
    })
    session = resp.json()["session"]
    resp = client.post(f"/api/imports/session/{session['id']}/orphans", json={"accept": False})
    body = resp.json()
    assert body["candidates"] == []
    assert body["session"]["orphans_done"] is True


def test_orphans_ya_resueltos_404_no_duplica(client, monkeypatch):
    _no_net_similarity(monkeypatch)
    resp = client.post("/api/imports/clusterize", json={
        "files": [{"name": "cv.txt", "kind": "text", "content": "- Diseñé la red."}],
    })
    session = resp.json()["session"]
    sid = session["id"]
    client.post(f"/api/imports/session/{sid}/orphans", json={"accept": True})
    resp = client.post(f"/api/imports/session/{sid}/orphans", json={"accept": False})
    assert resp.status_code == 200
    assert resp.json()["candidates"] == []


def test_sesion_inexistente_404(client):
    assert client.get("/api/imports/session/no_existe").status_code == 404