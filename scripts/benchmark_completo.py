"""
Benchmark completo de SIGEDOC:
1. Reinicia la semilla local y genera 1,200 documentos realistas con movimientos,
   expedientes (MongoDB) y cadenas SIGUIENTE (Neo4j) usando herramientas.medir.
2. Mide Trazabilidad (500 búsquedas aleatorias: % ubicados en 1 consulta, pérdidas, latencia).
3. Mide Rendimiento por motor (PostgreSQL, MongoDB, Neo4j e Integrado 3 bases) en:
   - Conectividad (ping)
   - Consulta puntual por ID
   - Consulta compleja / de negocio
Guarda todo en resultados_benchmark.json.
"""
import json
import math
import os
import random
import sys
import time
from pathlib import Path

BACKEND = Path(r"C:\Users\jojua\OneDrive\Documentos\Proyectos 7°\saas_documents\backend")
sys.path.insert(0, str(BACKEND))

# Forzar entorno local (Docker) sin tocar el .env de la nube
for k, v in {
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_PORT": "5433",
    "POSTGRES_DB": "sigedoc",
    "POSTGRES_USER": "sigedoc",
    "POSTGRES_PASSWORD": "cambia-esta-clave-postgres",
    "MONGO_URI": "mongodb://127.0.0.1:27018",
    "MONGO_DB": "sigedoc",
    "MONGO_USER": "sigedoc",
    "MONGO_PASSWORD": "cambia-esta-clave-mongo",
    "NEO4J_URI": "bolt://127.0.0.1:7687",
    "NEO4J_USER": "neo4j",
    "NEO4J_PASSWORD": "cambia-esta-clave-neo4j",
    "API_CORS_ORIGEN": "http://localhost:5173",
}.items():
    os.environ[k] = v

import psycopg
from neo4j import GraphDatabase
from pymongo import MongoClient

from app.config import Ajustes
from herramientas import esquemas, medir

OUT_DIR = Path(r"C:\Users\jojua\.gemini\antigravity\brain\a35aeabd-62de-4f0e-aba6-87d1bac23d6d")


def pct(vals: list[float], p: float) -> float:
    s = sorted(vals)
    return round(s[max(0, math.ceil(p * len(s)) - 1)] * 1000, 1)


def main() -> None:
    ajustes = Ajustes(_env_file=None)
    pg_dsn = (
        f"host={ajustes.postgres_host} port={ajustes.postgres_port} "
        f"dbname={ajustes.postgres_db} user={ajustes.postgres_user} "
        f"password={ajustes.postgres_password.get_secret_value()}"
    )
    pg, mongo, grafo = esquemas.conectar(ajustes)
    pg.row_factory = psycopg.rows.dict_row
    db = mongo[ajustes.mongo_db]
    col = db["expedientes"]

    print("1. Verificando volumen de 1,200+ documentos...", flush=True)
    ids = [r["id"] for r in pg.execute("SELECT id_documento::text AS id FROM documento").fetchall()]
    movs = pg.execute("SELECT COUNT(*) AS n FROM movimiento").fetchone()["n"]
    if len(ids) < 1200:
        esquemas.vaciar_datos(pg, db, grafo)
        esquemas.cargar_semilla(pg, db, grafo)
        volumen = medir.generar_volumen(pg, db, grafo, semanas=4, por_semana=300)
        ids = volumen["ids"]
        movs = volumen["movimientos"]
    print(f"   Volumen listo: {len(ids)} documentos, {movs} movimientos.", flush=True)

    # ── 2. Prueba de Trazabilidad (500 búsquedas) ─────────────────────────────
    print("2. Ejecutando 500 búsquedas de trazabilidad...", flush=True)
    rng = random.Random(42)
    muestras_traz = [rng.choice(ids) for _ in range(500)]
    ubicados_completos = 0
    perdidos = 0
    t_traz = []

    for did in muestras_traz:
        t0 = time.perf_counter()
        doc_pg = pg.execute(
            "SELECT d.id_documento, d.estado, "
            "(SELECT COUNT(*) FROM movimiento m0 WHERE m0.id_documento = d.id_documento) AS total_movs, "
            "m.id_area_destino, m.id_persona "
            "FROM documento d "
            "LEFT JOIN movimiento m ON m.id_documento = d.id_documento "
            "WHERE d.id_documento = %s ORDER BY m.fecha_hora DESC LIMIT 1",
            (did,),
        ).fetchone()
        exp_mg = col.find_one({"_id": did}, {"_id": 1, "tipo": 1})
        with grafo.session() as s:
            rec_nj = s.run(
                "MATCH (d:Documento {id: $id}) "
                "OPTIONAL MATCH (m:Movimiento)-[:SOBRE]->(d) "
                "RETURN d.id AS id, count(m) AS pasos",
                id=did,
            ).single()
        t_traz.append(time.perf_counter() - t0)

        if (
            doc_pg
            and exp_mg
            and rec_nj
            and rec_nj["id"] == did
            and rec_nj["pasos"] == doc_pg["total_movs"]
        ):
            ubicados_completos += 1
        else:
            perdidos += 1

    trazabilidad = {
        "busquedas": len(muestras_traz),
        "ubicados_completos": ubicados_completos,
        "porcentaje_ubicados": round(ubicados_completos * 100 / len(muestras_traz), 2),
        "perdidos": perdidos,
        "p50_ms": pct(t_traz, 0.5),
        "p95_ms": pct(t_traz, 0.95),
    }
    print(f"   Trazabilidad: {trazabilidad}", flush=True)

    # ── 3. Rendimiento por motor (50 repeticiones + 5 warmup) ─────────────────
    print("3. Midiendo rendimiento por motor (PG, Mongo, Neo4j, 3 bases)...", flush=True)
    muestras_50 = random.Random(7).sample(ids, 50)

    def bench(fn):
        for i in range(5):
            fn(muestras_50[i])
        tiempos = []
        for did in muestras_50:
            t0 = time.perf_counter()
            fn(did)
            tiempos.append(time.perf_counter() - t0)
        return {"p50": pct(tiempos, 0.5), "p95": pct(tiempos, 0.95)}

    ping_pg = bench(lambda _: pg.execute("SELECT 1").fetchone())
    ping_mg = bench(lambda _: mongo.admin.command("ping"))
    ping_nj = bench(lambda _: grafo.execute_query("RETURN 1"))

    id_pg = bench(lambda did: pg.execute("SELECT * FROM documento WHERE id_documento = %s", (did,)).fetchone())
    id_mg = bench(lambda did: col.find_one({"_id": did}))
    id_nj = bench(lambda did: grafo.execute_query("MATCH (d:Documento {id: $id}) RETURN d", id=did))

    cx_pg = bench(lambda _: pg.execute(
        "SELECT id_documento, sintesis, estado FROM documento WHERE sintesis ILIKE %s ORDER BY fecha_registro DESC LIMIT 50",
        ("%oficio%",),
    ).fetchall())
    cx_mg = bench(lambda _: list(col.find({"tipo": "oficio"}).sort("actualizado_en", -1).limit(50)))
    cx_nj = bench(lambda did: grafo.execute_query(
        "MATCH (m:Movimiento)-[:SOBRE]->(d:Documento {id: $id}) "
        "OPTIONAL MATCH (m)-[:SIGUIENTE*0..15]->(sig:Movimiento) RETURN m.id, sig.id",
        id=did,
    ))
    cx_3b = bench(lambda did: (
        pg.execute("SELECT * FROM documento WHERE id_documento = %s", (did,)).fetchone(),
        col.find_one({"_id": did}),
        grafo.execute_query(
            "MATCH (m:Movimiento)-[:SOBRE]->(d:Documento {id: $id}) "
            "OPTIONAL MATCH (m)-[:SIGUIENTE*0..15]->(sig:Movimiento) RETURN m.id, sig.id",
            id=did,
        ),
    ))

    resultados = {
        "volumen": {"documentos": len(ids), "movimientos": movs},
        "trazabilidad": trazabilidad,
        "rendimiento": {
            "ping": {"pg": ping_pg, "mongo": ping_mg, "neo4j": ping_nj},
            "puntual_id": {"pg": id_pg, "mongo": id_mg, "neo4j": id_nj},
            "compleja": {"pg": cx_pg, "mongo": cx_mg, "neo4j": cx_nj, "tres_bases": cx_3b},
        },
    }
    (OUT_DIR / "resultados_benchmark.json").write_text(json.dumps(resultados, indent=2), encoding="utf-8")
    print("4. Guardado en resultados_benchmark.json", flush=True)
    print(json.dumps(resultados, indent=2))

    pg.close()
    mongo.close()
    grafo.close()


if __name__ == "__main__":
    main()
