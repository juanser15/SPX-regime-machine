# SPX Regime Machine: funcionamiento y límites actuales

> **Alcance de este documento.** Describe el código presente en el workspace, los artefactos de datos existentes y las respuestas observadas en la URL publicada al redactarlo. No es una especificación de funcionalidades futuras ni una afirmación de que una versión nueva esté publicada. No se descargaron datos de Yahoo, no se ejecutó un refresh y no se modificaron las señales para preparar este documento.

## 1. Resumen ejecutivo

En este proyecto conviven **dos productos analíticos distintos**:

1. **Señal diaria FREE de régimen de SPX** (`free_daily_regime_v1`). Utiliza cierres diarios reales obtenidos de Yahoo Finance de SPX y series de volatilidad. Calcula puntajes causales de estrés de 0 a 100 y clasifica cada fecha como `RISK-ON`, `NEUTRAL` o `DE-RISK`. Es **investigación histórica**: ni el feed de Yahoo ni las 4.146 señales conservadas prueban que cada resultado haya sido registrado en vivo en su fecha. La API nueva permite consultar este historial con metadatos *point-in-time* (PIT), pero no lo entrega como una señal operativa.
2. **Dashboard intradía de flujo de opciones**. Simula precios, operaciones de opciones y una estrategia para investigar visualizaciones y métricas. **Sus datos intradía son sintéticos**. No recibe una cadena de opciones real ni genera los eventos diarios canónicos que consume la API. En la misma interfaz hay un panel separado para la señal diaria real de Yahoo.

El servidor Express implementa en el workspace un contrato de lectura `regime.signal.v3` con historial, consulta `as-of`, provenance, health y `latest` **exclusivamente live**. Los eventos y la metadata se guardan en PostgreSQL. No hay un proveedor live registrado; por eso el `latest` **correcto en el preview v3** es HTTP `503 NO_ELIGIBLE_LIVE_SIGNAL`. Esto no significa que haya desaparecido el historial de investigación.

**Diferencia crítica entre código y producción:** la aplicación publicada consultada, `https://spx-regime-machine.replit.app`, todavía respondió con la API anterior: `/api/capabilities` y `/api/signals/catalog` devolvieron `404`; `/api/signals/latest` devolvió `200` con `observation_mode: "historical_reconstruction"` y `live_recorded: false`; `/api/healthz` devolvió `{"status":"ok", ...}`. Por lo tanto, **no se puede decir que producción ya esté sirviendo v3**. La publicación y su comprobación posterior son pasos separados.

## 2. Mapa de piezas y flujo

```text
Yahoo Finance, cierres diarios
  → adaptador de ingestión (yfinance, 6 series)
  → filas diarias alineadas sin imputación + raw/coverage/manifiesto/snapshot
  → modelo free_daily_regime_v1 (features causales + scores)
  → CSV histórico + latest JSON + manifiesto de señal + snapshot de archivos
  → verificación de hash y consistencia de archivos
  → PostgreSQL: eventos, estado de fuente, intentos de ingestión
  → API v3: research history / as-of / provenance / health
                  ╰→ latest operativo: SOLO evento live elegible

Generador sintético intradía → Streamlit: gráficos, Flow Score y evaluación
Panel FREE en Streamlit ← archivos locales de señal diaria (NO la tabla de la API)
```

**Dos caminos de actualización que no hay que confundir:**

- El botón **“Refresh Yahoo signal”** de Streamlit llama directamente al cálculo Python y escribe `spx-flow-machine/data/free_signal/`. Esto actualiza los archivos que muestra el panel FREE, **pero no publica automáticamente filas nuevas en PostgreSQL ni cambia la respuesta de la API**.
- El comando one-shot `pnpm --filter @workspace/api-server run refresh:once` crea una salida temporal, la verifica y publica filas/metadata/run en PostgreSQL. **No reescribe los archivos permanentes que lee el dashboard**. Además, no existe hoy un scheduler de producción configurado que lo invoque por sí solo.

El consumidor privado **Signal Hub** no está en este workspace. Se define cómo debería consumir el contrato, pero **no está verificada su integración backend real**.

## 3. Entradas de la señal diaria real

### 3.1. Origen y formato

El adaptador pide a `yfinance` barras diarias (`interval="1d"`) y usa la columna **`Close` sin ajuste automático** (`auto_adjust=False`). `start` es inclusivo según la consulta; `end` es **exclusivo**. La tabla canónica generada tiene una columna `date` y seis cierres:

| Ticker Yahoo | Campo canónico | Rol |
| --- | --- | --- |
| `^GSPC` | `spx_close` | Core |
| `^VIX` | `vix_close` | Core |
| `^SKEW` | `skew_close` | Core |
| `^VIX9D` | `vix9d_close` | Augmented/opcional |
| `^VIX3M` | `vix3m_close` | Augmented/opcional |
| `^VVIX` | `vvix_close` | Augmented/opcional |

Se preservan los payloads crudos, sus hashes y un reporte de cobertura por serie. Las fechas se alinean por unión de los calendarios observados; los valores ausentes se mantienen como ausentes. **No se hace forward-fill ni interpolación** para “inventar” un cierre.

El refresh diario acepta `--start` (por defecto `2010-01-01`), `--end` (obligatorio y exclusivo) y `--output-dir` (por defecto `spx-flow-machine/data/free_signal`). El scheduler aplica por defecto el mismo inicio y calcula un `end` posterior a la fecha de ejecución.

### 3.2. Política ante entradas ausentes

- Si falla globalmente la descarga, validación o disponibilidad utilizable de cualquiera de las series **core**, el adaptador registra el fallo y **aborta** el refresh. No sustituye SPX/VIX/SKEW con valores ficticios.
- Si falla globalmente una serie **opcional**, el refresh de la señal diaria permite continuar, registra la serie/motivo como no disponible y marca las observaciones correspondientes como degradadas.
- También puede haber **huecos en fechas concretas**, incluso dentro de una serie obtenida. Cada fila de señal evalúa sus seis campos de entrada de **esa fecha**, registra `missing_inputs` y asigna `data_quality: COMPLETE` o `DEGRADED_MISSING_INPUTS`; la etiqueta de carril es `AUGMENTED` o `CORE_FREE_DEGRADED`. Un fallo global de serie core y un hueco puntual no son la misma condición.
- Una fila con suficientes componentes para obtener un puntaje puede quedar en el **historial research** aunque haya componentes faltantes: debe leerse su calidad/missing inputs, no asumirse calidad completa por existir un score.
- Independientemente de que haya cero faltantes, el **origen Yahoo sigue siendo solo investigación**: las futuras salidas generadas por este código indican `research_status: RESEARCH_ONLY` y `deployable: false`. `COMPLETE` describe cobertura de componentes, **no** habilitación operativa live.

### 3.3. Ejemplar de datos ya existente

Los archivos persistidos que se conservaron contienen **4.146 filas de señal**, con sesiones del `2010-03-30` al `2026-09-18`. La última fila guardada es `NEUTRAL`, score general aproximadamente `44,95`, confianza `LOW`; la recuperación del input figura en `2026-09-18T22:03:55Z` y el manifiesto de señal en `2026-09-18T22:03:59Z`. Se pidieron datos hasta `2026-09-19` **exclusivo**. Estas cifras describen el snapshot existente, **no una cotización actual**.

Los archivos fueron generados **antes** de algunos campos de calidad/política incorporados al código nuevo. Por ejemplo, su `signal_manifest.json` conserva `input_source: "Yahoo Finance"` y no contiene `deployable`; **no se alteraron retroactivamente las 4.146 señales para fingir que ya se recalcularon**. Las salidas de un refresh futuro llevarían la nueva metadata por fecha.

## 4. Transformación: qué calcula `free_daily_regime_v1`

1. **Features trailing**: retornos de SPX a 1/5/20/60 sesiones, distancia a media móvil de 20, drawdown frente a máximo móvil de 252, volatilidad realizada a 10/20/60, nivel y cambio a 5 días del VIX, cocientes VIX9D/VIX y VIX/VIX3M, niveles de VVIX y SKEW.
2. Cada componente de estrés se convierte a un **percentil empírico móvil de 252 observaciones**, con mínimo de 60. Solo usa la información fechada hasta la sesión evaluada; no usa etiquetas futuras para calcular el régimen diario.
3. El bloque **body** combina: tendencia débil de SPX (peso 25%), drawdown (25%), volatilidad realizada a 20 días (20%), nivel de VIX (20%) y aceleración de VIX (10%).
4. El bloque **tail hazard** combina: SKEW (30%), VVIX (30%), inversión VIX9D/VIX (20%) e inversión VIX/VIX3M (20%). Si faltan componentes, el promedio ponderado se renormaliza **entre los disponibles**, en lugar de asignarles un valor artificial. Si el bloque tail no se puede calcular, el score general usa body; en caso contrario, `overall = 0,75 × body + 0,25 × tail`.
5. Bandas fijas de `overall_stress_score`:
   - `≤ 35`: `RISK-ON`, régimen `CALM / RISK-ON`;
   - `> 35` y `< 65`: `NEUTRAL`, `TRANSITION / NEUTRAL`;
   - `≥ 65`: `DE-RISK`, `STRESS / RISK-OFF`.
   Las fechas sin score general no se publican en el CSV de historia de señales.
6. `confidence_score` combina distancia del score a 50 (65% del puntaje) y cobertura de los nueve componentes (35%). `confidence`: `LOW` si es menor a 45, `MEDIUM` entre 45 y menos de 70, `HIGH` a partir de 70. `primary_drivers` enumera hasta tres componentes más alejados de 50, con dirección del efecto.

**Interpretación esencial:** `overall_stress_score`, `body_stress_score`, `tail_risk_hazard_score` y `confidence_score` son **scores heurísticos/percentiles, no probabilidades calibradas**, pronósticos garantizados ni órdenes de trading. El campo `probability_status` es `NOT_CALIBRATED`. No hay datos reales de flujo de opciones dentro de esta señal FREE.

## 5. Salidas de Python y persistencia

Al hacer refresh de la señal diaria, el programa genera:

| Salida | Contenido y uso |
| --- | --- |
| `daily_data/raw/*.csv` | Descargas por ticker para auditoría; cada serie tiene hash de payload en su manifiesto. |
| `daily_data/canonical_daily.csv` | Tabla alineada por `date` con los seis cierres y huecos explícitos. |
| `daily_data/coverage_report.json` | Primer/último dato válido, observaciones y faltantes por serie, además de controles de cobertura. |
| `daily_data/metadata_manifest.json` | Fuente, hora de recuperación, series disponibles/no disponibles, checksums y `input_data_snapshot_id`. |
| `daily_data/snapshots/<input_data_snapshot_id>/` | Copias inmutables del conjunto de entrada, si es un snapshot nuevo. |
| `signal_history.csv` | Una fila por sesión puntuable: fecha, carril, régimen, riesgo, scores, confianza, calidad, inputs faltantes, drivers y semántica del score. |
| `latest_signal.json` | Última **fila del CSV de investigación**, más metadata de recuperación/snapshot/modelo. Su nombre `latest` **no significa live**; no es el mismo recurso que `/api/signals/latest`. |
| `signal_manifest.json` | Versión del modelo, rango solicitado, fecha de cálculo, fuente, snapshots, hash SHA-256 del CSV de señales, bandas, causalidad y metadata de calidad. |
| `snapshots/<signal_snapshot_id>/` | Copias inmutables del CSV, latest JSON y manifiesto cuando aparece un nuevo snapshot. |

Un proceso separado verifica el hash del historial y que el `latest_signal.json` corresponda a la última fila antes de incorporar la salida a PostgreSQL. En la base existen tablas de **eventos**, **intentos de ingestión** y **estado de la fuente**. La primera carga de una base vacía conserva las 4.146 filas del artefacto verificado. En bases existentes se normaliza metadata faltante de registros viejos sin cambiar su `event_id` ni el payload de señal.

## 6. Qué significa cada timestamp de un evento API

| Campo | Significado | Precaución |
| --- | --- | --- |
| `session_date` / `date` | Sesión a la que se refiere la medición. | No es la fecha en que fue vista por el sistema. |
| `market_as_of` | Referencia a las 16:00 de Nueva York de esa sesión (con ajuste horario). | Una reconstrucción hecha años después **no era observable en ese cierre**. |
| `source_retrieved_at` | Cuándo se recuperó el snapshot de fuente. | Es una hora real del conjunto usado; no da una “vintage” histórica live de Yahoo. |
| `computed_at` | Cuándo se generó el manifiesto/resultado. | Es posterior a la descarga; para backfills puede ser años después de `session_date`. |
| `observation_at` | Para Yahoo reconstruido, se fija a la recuperación. | No se sustituye por `market_as_of` para fabricar observación histórica. |
| `available_at` | Disponibilidad PIT conservadora: **máximo** entre cierre de sesión + 6 horas, recuperación y cálculo. | `as-of` no debe exponer un evento antes de este instante. |
| `valid_from` / `valid_until` | Ventana de vigencia metadata; `valid_from` no antecede disponibilidad y `valid_until` se fija a 72 horas después de ella. | Pasado `valid_until`, un evento no es elegible como *latest operativo*; sigue consultable en history research. |
| `ingested_at` | Hora de incorporación; para filas migradas puede reconstruirse a partir de la recuperación. | No tomarla por prueba de registro live original. |

Además, cada respuesta de fila expone `event_id`, `revision_id`, `input_data_snapshot_id`, `signal_snapshot_id`, checksums de input/config/datos/fila, `provider_lineage`, `provenance`, `observation_mode`, `source_mode`, `live_recorded`, `research_only`, `freshness` y `quality`. El `event_id` legado es determinístico con la identidad original v2, modelo, sesión y snapshot de entrada; **el contrato público v3 no obliga a reidentificar los 4.146 eventos**. Para no confundir conceptos, `data_quality` describe los inputs del score y `quality` es metadata de la fila persistida (por ejemplo `VERIFIED`).

## 7. API del workspace: entradas HTTP y salidas

Todas las rutas son públicas de **consulta**, están bajo `/api` y devuelven `Cache-Control: private, no-store`. La fuente de verdad de sus tipos es `lib/api-spec/openapi.yaml`; se generan el cliente TypeScript y las validaciones Zod. Las respuestas de señales se validan antes de enviarse. No se requiere login ni token para consultar. **Matiz técnico:** la primera lectura puede cargar en PostgreSQL un artefacto verificado si la tabla está vacía, o completar metadata heredada si ya había filas; no es un refresh de mercado solicitado por el consumidor.

| GET | Entrada | Salida / comportamiento |
| --- | --- | --- |
| `/api/capabilities` | Sin parámetros. | `regime.signal.v3`, modos, campos PIT, orden, filtros, límites de paginación y SLA declarada de 72 h. Declara la **capacidad** de `LIVE_REGISTERED`, no que haya un proveedor conectado. |
| `/api/signals/catalog` | Sin parámetros. | Modelos persistidos y primer/último `session_date` con conteo. |
| `/api/signals/history` | `start` y `end` opcionales (`YYYY-MM-DD`, inclusivos), `model_version`, `as_of` ISO con zona horaria, `limit` (1–1000, por defecto 100), `cursor`. | `data` de investigación, `count` de la página, `total` filtrado, `next_cursor`, rango, modelo y modo(s). Orden ascendente `(session_date, event_id)`. Puede contener filas reconstruidas y, si un día existieran, filas live; **el modo de cada fila es el decisivo**. |
| `/api/signals/as-of` | `as_of` **obligatorio**; acepta además filtros y paginación de history. | El mismo tipo de historial, restringido a filas cuyo `available_at` **y** `computed_at` sean `≤ as_of`. El instante exacto del límite es inclusivo. No consulta “cómo estaba Yahoo entonces” si el snapshot fue obtenido después. |
| `/api/signals/provenance` | Sin parámetros. | Fuente, modelo, rango solicitado, fecha de recuperación, límites/conteo del libro, hash de historia, IDs de snapshot, `NOT_CALIBRATED` y lineage por serie (ticker, cobertura, hash crudo). Lee la metadata del snapshot publicado en DB; fallback a archivos solo si corresponde al mismo snapshot. Si no puede completar la provenance, responde `503`, no inventa hashes. |
| `/api/signals/latest` | Sin parámetros. | **Solo** un evento `LIVE_REGISTERED` con `live_recorded=true`, `freshness=FRESH`, proveedor no Yahoo con lineage, disponibilidad/cálculo/observación no futuros, ventana `valid_from ≤ ahora < valid_until` y recuperación dentro de 72 h. Si no existe: `503` con código `NO_ELIGIBLE_LIVE_SIGNAL`; jamás usa la última reconstrucción como reemplazo. |
| `/api/healthz` | Sin parámetros. | Estado general y bloques independientes: integridad de artefactos, conectividad DB, frescura de fuente, último cómputo programado, persistencia y elegibilidad para Hub; incluye bloqueos, edades, fechas y próxima hora esperada. |

Errores de fecha, `as_of`, límite o cursor se expresan como `400` con `{ "error": { "code": "...", "message": "..." } }`. La ausencia de un live elegible no hace fallar history. Un error de DB, provenance incompleta o una fila obligatoria incompleta puede dar `503`.

**Ejemplo esquemático de lectura de historia (campos abreviados, no una nueva señal):**

```json
{
  "contract_version": "regime.signal.v3",
  "total": 4146,
  "count": 1,
  "data": [{
    "date": "2010-03-30",
    "session_date": "2010-03-30",
    "model_version": "free_daily_regime_v1",
    "observation_mode": "HISTORICAL_RECONSTRUCTION",
    "live_recorded": false,
    "research_only": true,
    "observation_at": "2026-09-18T22:03:55.000Z",
    "available_at": "2026-09-18T22:03:59.000Z",
    "risk_signal": "NEUTRAL",
    "probability_status": "NOT_CALIBRATED"
  }],
  "next_cursor": "..."
}
```

En ese ejemplo, **la sesión de 2010 solo se volvió visible para este libro al reconstruirse en 2026**. El campo `risk_signal` es ilustrativo, no una atribución verificada a esa fecha: consultar la fila real para su valor. Los endpoints reales incluyen más campos que el extracto.

### Interpretación de health y freshness

- El SLA de fuente es **72 horas desde `last_retrieved_at`**. `source_freshness: FRESH` habla de edad de la fuente, **no** transforma datos Yahoo en live.
- `computation` se basa en una ejecución programada **exitosa**, no en que exista el backfill original.
- `hub_eligibility: READY` requiere un evento que supere el filtro de `latest`. Con el proveedor actual, se debe esperar un bloqueo.
- `status: STALE` con HTTP `200` significa que siguen disponibles las lecturas históricas, **no** que Signal Hub pueda tomar una nueva decisión operativa. `ERROR`/`503` señala, entre otras cosas, problemas de integridad, persistencia o conexión.
- El valor `freshness` persistido por fila y la edad dinámica reportada por health **no son intercambiables**. Un evento viejo puede continuar visible en history aunque haya caducado.

## 8. Ejecución programada, fallos y publicación de datos

Hay **lógica para ejecutar** un refresh, no un servicio autónomo ya desplegado. El proceso one-shot:

1. Verifica si es un día de semana y al menos las **18:00 de Nueva York**; antes o durante fin de semana devuelve `SKIPPED`. El chequeo **no incluye un calendario de feriados bursátiles**.
2. Obtiene un advisory lock de PostgreSQL para evitar solapamiento. Registra un intento `RUNNING` con una lease de 15 minutos; un proceso posterior puede marcar un intento abandonado como fallido.
3. Puede intentar hasta **tres veces** (esperas exponenciales: 30 y 60 segundos antes del tercer intento, máximo configurable 5 minutos). Descarga y recalcula desde 2010 en un directorio temporal descartable. Requiere Python, las librerías instaladas, conectividad a Yahoo y acceso a la **misma base** de datos que la API.
4. Verifica el staging, toma solo fechas posteriores al watermark máximo persistido y, en una **transacción de DB**, inserta eventos, publica metadata/provenance de la fuente y finaliza el intento exitoso. Un refresh sin nuevas fechas no debe adelantar snapshot ni watermark. En un fallo previo a la transacción, la publicación anterior permanece.
5. Elimina el staging temporal. Un refresh exitoso de Yahoo **sigue publicando solo investigación**, no un `LIVE_REGISTERED`.

**Durabilidad real:** el lock, las leases, la tabla de runs y la transacción protegen intentos que **alguien efectivamente invoque**. La API publicada es autoscale y no mantiene un timer duradero; **no hay job programado en producción**. Por eso no está garantizada una actualización diaria automática. El botón de Streamlit tampoco sustituye este proceso de publicación a DB.

## 9. Qué ve el dashboard intradía

El panel FREE de Streamlit **lee archivos locales**: `latest_signal.json` y `signal_history.csv`. Muestra riesgo, régimen, scores general/body/tail, confianza, fecha, carril/calidad, drivers, faltantes y las últimas diez filas. El botón “Refresh Yahoo signal” escribe nuevos archivos en ese mismo carril local, sujeto a disponibilidad de Yahoo.

La sección **Options Flow** restante es una simulación fija de una sesión intradía de ejemplo (`2024-01-15`, 09:30–16:00) con un precio inicial SPX de 4.800, operaciones de opciones generadas y sesgo débil inyectado. Controles: semilla (por defecto 42), regeneración, horizonte de 5 o 15 minutos, umbral y costo en puntos básicos. Su flujo pasa por trades sintéticos, enriquecimiento, agregación a barras, features, retornos futuros, `Flow Score` y evaluación de estrategia. Muestra precio, score, dirección, confianza, hit rates, PnL, gráficos de precio/score/retornos, tabla de barras y métricas de evaluación. **No son observaciones de OPRA ni un backtest con operaciones reales**; esta sección no alimenta el `free_daily_regime_v1` canónico.

## 10. Limitaciones para decidir próximos pasos

1. **Producción no coincide aún con el contrato del workspace.** La URL publicada todavía expone la API anterior que entrega una reconstrucción bajo `latest` y health `ok`. Antes de usar v3 como fuente canónica, hay que publicar el código actual, confirmar esquema/migración de DB aplicable y volver a inspeccionar sus endpoints. Hasta entonces, los resultados v3 del preview no describen lo que ve un consumidor de producción.
2. **No hay proveedor live verificable.** Existe una interfaz/política para distinguirlo, pero no un adaptador productivo que registre observaciones y vintages de inputs de un proveedor distinto de Yahoo. No se debe habilitar una señal operativa sustituyendo el `503` con una reconstrucción.
3. **No hay invocación programada durable en producción.** El one-shot existe; hacen falta scheduling independiente, empaquetado de Python/dependencias, conexión correcta a la DB productiva y verificación de runs/alertas. Un job sin nuevas fechas tampoco rejuvenece por sí mismo la hora de los datos existentes.
4. **Dos stores pueden divergir.** Streamlit lee archivos locales y la API lee PostgreSQL; el refresh del botón y el refresh programado no sincronizan ambos destinos. Son lecturas diferentes de “latest”.
5. **Yahoo y causalidad no son sinónimos de vintage live.** El modelo usa funciones rolling sin mirar sesiones futuras, pero una descarga histórica posterior no demuestra qué dato o revisión estaba disponible en cada cierre anterior. El `available_at` conservador evita afirmar lo contrario; no reconstruye una verdad live perdida.
6. **Cobertura y calidad deben leerse por fila.** El artefacto preservado no se recalculó con los campos nuevos de un refresh futuro. Las ausencias puntuales y la degradación afectan qué tan completo es un score; los pesos se renormalizan entre componentes disponibles. No confundir `COMPLETE`, `VERIFIED`, `FRESH` y `LIVE_REGISTERED`.
7. **El score no es probabilidad ni recomendación automática.** No hay calibración probabilística, PnL real del modelo diario, datos reales de cadena de opciones, gestión de riesgo de ejecución ni garantía de actualización en días feriados.
8. **Signal Hub no está verificado extremo a extremo.** Hay OpenAPI, cliente y pautas de consumo, pero el backend privado de Hub no figura aquí; no se puede certificar su validador, caché, UI, manejo de `503` ni configuración real solo desde este repositorio.
9. **Los tests del código no equivalen a una prueba productiva completa.** Hay tests Python, pruebas de repositorio/scheduler y comprobaciones HTTP de desarrollo previas. Este documento no ejecutó nuevas suites E2E ni un refresh real para acreditar scheduler, proveedor o despliegue productivo.

## 11. Decisiones para avanzar

Para elegir el siguiente trabajo, conviene resolver explícitamente:

1. **Destino del producto:** ¿queremos un **research feed diario** confiable y separado, o además una **señal live operativa** para Signal Hub? Lo segundo exige proveedor, política de vintage y criterios de elegibilidad comprobables.
2. **Fuente única de persistencia:** ¿el dashboard FREE debe leer la misma publicación en PostgreSQL que la API, o continuar siendo una vista de archivos experimentales separada? Hoy ambos caminos no están unidos.
3. **Operación productiva:** si se desea refresh autónomo, ¿dónde se ejecutará el job duradero, cómo compartirá la DB y cómo se observarán fallos/feriados/datos tardíos?
4. **Contrato con Hub:** confirmar en su backend privado los campos requeridos, error handling de `latest=503`, uso separado de history research y filtro PIT; recién entonces validar compatibilidad punta a punta.
5. **Publicación:** ejecutar el Publish de la versión nueva y comparar las rutas productivas con OpenAPI y el preview, sin asumir que publicar actualiza automáticamente un proveedor live o crea un scheduler.

## 12. Dónde está cada pieza

- Ingestión Yahoo y definición de tickers: `spx-flow-machine/src/yahoo_daily_adapter.py`.
- Features, modelo, calidad y generación de artefactos: `spx-flow-machine/src/daily_signal.py`.
- Artefactos históricos conservados: `spx-flow-machine/data/free_signal/`.
- Dashboard Streamlit: `spx-flow-machine/app.py`; generador intradía sintético: `spx-flow-machine/src/generate_dummy_data.py`.
- Esquema DB: `lib/db/src/schema/index.ts`; verificación de archivos: `artifacts/api-server/src/lib/signalStore.ts`.
- Escritura/lectura de eventos y política latest/as-of: `artifacts/api-server/src/lib/signalRepository.ts`.
- Política del scheduler y ejecutable one-shot: `artifacts/api-server/src/lib/signalScheduler.ts` y `artifacts/api-server/src/refresh.ts`.
- Rutas/health: `artifacts/api-server/src/routes/signals.ts` y `artifacts/api-server/src/routes/health.ts`.
- Contrato OpenAPI único: `lib/api-spec/openapi.yaml`; nota de integración: `SIGNAL_CONTROL_ROOM_INTEGRATION.md`.