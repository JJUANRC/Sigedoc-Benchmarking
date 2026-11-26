# SIGEDOC — Benchmarking y Evidencia de Trazabilidad

Repositorio dedicado a las pruebas reproducibles de **trazabilidad**, **rendimiento por motor** y **escalabilidad** de la arquitectura políglota de SIGEDOC (**PostgreSQL 17**, **MongoDB 8.0** y **Neo4j 5.26**).

## 1. Resumen de hallazgos

### Trazabilidad (500 búsquedas sobre 1,244 documentos y 3,066 movimientos)
- **Documentos localizados en 1 consulta:** **500 / 500 (100.0 %)** (ubicación actual, responsable, expediente documental y cadena completa de movimientos coincidente entre PostgreSQL y Neo4j).
- **Documentos perdidos o inconsistentes:** **0**.
- **Latencia de consulta integrada en bases de datos:** `p50 = 6.2 ms`, `p95 = 9.6 ms` *(vía API REST completa con serialización y autenticación en `evidencia.md`: `p50 = 34 ms`, `p95 = 63 ms`)*.

### Rendimiento por motor (1,244 documentos · 50 repeticiones por operación)

| Categoría | PostgreSQL (`p50` / `p95`) | MongoDB (`p50` / `p95`) | Neo4j (`p50` / `p95`) | 3 bases juntas (`p50` / `p95`) |
| --- | --- | --- | --- | --- |
| **Conectividad (ping)** | 0.9 ms / 2.9 ms | 0.9 ms / 1.5 ms | 3.7 ms / 5.2 ms | — |
| **Consulta puntual por ID** | 1.0 ms / 1.6 ms | 2.8 ms / 13.5 ms | 2.9 ms / 4.1 ms | — |
| **Consulta de negocio** | 2.5 ms / 2.9 ms | 3.2 ms / 3.6 ms | 3.9 ms / 7.5 ms | **8.3 ms / 10.5 ms** |

### Escalabilidad por volumen (1,000 a 100,000 documentos · 30 repeticiones)

| Volumen | PostgreSQL (`p50` / `p95`) | MongoDB (`p50` / `p95`) | Neo4j (`p50` / `p95`) |
| --- | --- | --- | --- |
| **1,000 docs ($10^3$)** | 2.4 ms / 18.9 ms | 3.7 ms / 20.5 ms | 19.6 ms / 51.0 ms |
| **10,000 docs ($10^4$)** | 8.6 ms / 16.4 ms | 7.3 ms / 12.7 ms | 14.3 ms / 23.5 ms |
| **50,000 docs** | 37.8 ms / 74.0 ms | 26.0 ms / 41.6 ms | 13.4 ms / 18.8 ms |
| **100,000 docs ($10^5$)** | 65.1 ms / 97.2 ms | 33.6 ms / 56.5 ms | 5.7 ms / 13.4 ms |

## 2. Estructura del repositorio
- `scripts/benchmark_completo.py`: prueba de trazabilidad (500 búsquedas) y rendimiento individual de PostgreSQL, MongoDB, Neo4j y consulta integrada.
- `scripts/medir_escalabilidad_100k.py`: prueba de carga incremental de 1,000 a 100,000 documentos.
- `datos/resultados_benchmark.json`: salida cruda de trazabilidad y rendimiento por motor.
- `datos/escalabilidad_100k.json`: salida cruda de la curva de escalabilidad.

## 3. Cómo reproducir
Con los contenedores de PostgreSQL, MongoDB y Neo4j activos:
```bash
python scripts/benchmark_completo.py
python scripts/medir_escalabilidad_100k.py
```
