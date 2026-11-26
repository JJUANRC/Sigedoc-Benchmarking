"""
Mide la escalabilidad real de PostgreSQL, MongoDB y Neo4j a:
1,000, 10,000, 50,000 y 100,000 documentos.
Usa COPY en PostgreSQL, insert_many por lotes en MongoDB y UNWIND por lotes en Neo4j.
"""
import json
import math
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from neo4j import GraphDatabase
from pymongo import MongoClient

PG_DSN = "host=127.0.0.1 port=5433 dbname=sigedoc user=sigedoc password=cambia-esta-clave-postgres connect_timeout=10"
MONGO_URI = "mongodb://sigedoc:cambia-esta-clave-mongo@127.0.0.1:27018"
NEO4J_URI = "bolt://127.0.0.1:7687"
NEO4J_AUTH = ("neo4j", "cambia-esta-clave-neo4j")

VOLUMENES = [1000, 10000, 50000, 100000]
WARMUP = 3
N_MEDICIONES = 30
OUT_DIR = Path(r"C:\Users\jojua\.gemini\antigravity\brain\a35aeabd-62de-4f0e-aba6-87d1bac23d6d")
ACTORES = [
    "00000000-0000-4000-8000-000000000601",
    "00000000-0000-4000-8000-000000000602",
]


def pct(vals: list[float], p: float) -> float:
    s = sorted(vals)
    val_ms = s[max(0, math.ceil(p * len(s)) - 1)] * 1000
    return round(val_ms, 1)


def limpiar_sinteticos(pg, mongo_db, driver) -> None:
    print("Limpiando documentos sintéticos previos...")
    with pg.transaction():
        pg.execute("DELETE FROM documento WHERE numero_emisor LIKE 'SC-%'")
    mongo_db["expedientes"].delete_many({"_id": {"$not": {"$regex": "^00000000-"}}})
    with driver.session() as s:
        # Borrar en lotes para no saturar memoria de Neo4j
        while True:
            res = s.run(
                "MATCH (d:Documento) WHERE NOT d.id STARTS WITH '00000000-' "
                "WITH d LIMIT 10000 DETACH DELETE d RETURN count(*) AS n"
            ).single()
            if not res or res["n"] == 0:
                break


def insertar_lote(pg, mongo_db, driver, cantidad: int, offset_inicial: int) -> None:
    if cantidad <= 0:
        return
    ids = [str(uuid.uuid4()) for _ in range(cantidad)]
    ahora = datetime.now(UTC)

    # 1. PostgreSQL via COPY
    with pg.transaction():
        with pg.cursor() as cur:
            with cur.copy(
                "COPY documento (id_documento, sentido, tipo, numero_emisor, id_actor_emisor, "
                "fecha_documento, sintesis, confidencial, estado, canal_inicial, "
                "fecha_recepcion_inicial, fecha_recepcion_oficial) FROM STDIN"
            ) as copy:
                for i, did in enumerate(ids):
                    idx = offset_inicial + i + 1
                    copy.write_row((
                        did,
                        "entrada",
                        "oficio",
                        f"SC-{idx:07d}",
                        ACTORES[i % 2],
                        "2024-01-15",
                        f"Documento de escala {idx}",
                        False,
                        "en_tramite",
                        "papel",
                        "2024-01-15",
                        "2024-01-15",
                    ))

    # 2. MongoDB en lotes de 10,000
    col = mongo_db["expedientes"]
    for start in range(0, len(ids), 10000):
        batch = [
            {
                "_id": did,
                "tipo": "oficio",
                "datos_tipo": {},
                "anexos": [],
                "notas": [],
                "referencias_citadas": [],
                "creado_en": ahora,
                "actualizado_en": ahora,
            }
            for did in ids[start : start + 10000]
        ]
        col.insert_many(batch, ordered=False)

    # 3. Neo4j en lotes de 5,000
    with driver.session() as s:
        for start in range(0, len(ids), 5000):
            chunk = ids[start : start + 5000]
            s.run(
                "UNWIND $ids AS id CREATE (:Documento {id: id, folio: id, estado: 'en_tramite'})",
                ids=chunk,
            )


def medir_pg(pg) -> float:
    t0 = time.perf_counter()
    pg.execute(
        "SELECT id_documento, numero_emisor, sintesis FROM documento "
        "WHERE estado = 'en_tramite' AND sintesis ILIKE %s "
        "ORDER BY fecha_registro DESC LIMIT 50",
        ("%escala%",),
    ).fetchall()
    return time.perf_counter() - t0


def medir_mongo(col) -> float:
    t0 = time.perf_counter()
    list(col.find({"tipo": "oficio"}).sort("actualizado_en", -1).limit(50))
    return time.perf_counter() - t0


def medir_neo4j(driver) -> float:
    t0 = time.perf_counter()
    with driver.session() as s:
        list(s.run("MATCH (d:Documento {estado: 'en_tramite'}) RETURN d.id LIMIT 50"))
    return time.perf_counter() - t0


def main() -> None:
    pg = psycopg.connect(PG_DSN, row_factory=psycopg.rows.dict_row)
    mongo = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
    mongo_db = mongo["sigedoc"]
    col = mongo_db["expedientes"]
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)

    limpiar_sinteticos(pg, mongo_db, driver)
    actual = pg.execute("SELECT COUNT(*) AS n FROM documento").fetchone()["n"]
    print(f"Base inicial: {actual} documentos")

    resultados = {}
    for vol in VOLUMENES:
        faltan = vol - actual
        print(f"\n── Insertando {faltan:,} para llegar a {vol:,} documentos ──", flush=True)
        t_ins = time.perf_counter()
        insertar_lote(pg, mongo_db, driver, faltan, actual)
        actual = vol
        print(f"   Carga lista en {time.perf_counter() - t_ins:.1f} s. Midiendo...", flush=True)

        for _ in range(WARMUP):
            medir_pg(pg)
            medir_mongo(col)
            medir_neo4j(driver)

        t_pg = [medir_pg(pg) for _ in range(N_MEDICIONES)]
        t_mg = [medir_mongo(col) for _ in range(N_MEDICIONES)]
        t_nj = [medir_neo4j(driver) for _ in range(N_MEDICIONES)]

        resultados[vol] = {
            "pg":    {"p50": pct(t_pg, 0.5), "p95": pct(t_pg, 0.95)},
            "mongo": {"p50": pct(t_mg, 0.5), "p95": pct(t_mg, 0.95)},
            "neo4j": {"p50": pct(t_nj, 0.5), "p95": pct(t_nj, 0.95)},
        }
        print(
            f"   PG: p50={resultados[vol]['pg']['p50']} ms, p95={resultados[vol]['pg']['p95']} ms | "
            f"Mongo: p50={resultados[vol]['mongo']['p50']} ms, p95={resultados[vol]['mongo']['p95']} ms | "
            f"Neo4j: p50={resultados[vol]['neo4j']['p50']} ms, p95={resultados[vol]['neo4j']['p95']} ms",
            flush=True,
        )

    (OUT_DIR / "escalabilidad_100k.json").write_text(json.dumps(resultados, indent=2))
    print("\nGuardado en escalabilidad_100k.json")
    pg.close()
    mongo.close()
    driver.close()


if __name__ == "__main__":
    main()
