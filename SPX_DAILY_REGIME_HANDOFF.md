# SPX Daily Regime Research — estado actual y propuestas

## 1. Resumen ejecutivo

El proyecto contiene hoy dos líneas separadas:

1. **Daily Data Foundation con datos reales de Yahoo Finance.** Descarga, valida, alinea y versiona series diarias. Todavía no genera señales, estados de mercado ni recomendaciones de trading.
2. **Dashboard intradía de options flow con datos sintéticos.** Demuestra un pipeline técnico y visual, pero no contiene opciones reales y sus resultados no deben interpretarse como evidencia de trading.

La recomendación es continuar el trabajo de regímenes exclusivamente sobre la línea diaria real. El pipeline sintético debe permanecer aislado.

---

## 2. Datos reales disponibles

### Fuente

Yahoo Finance mediante `yfinance`, sin API key.

### Series

| Serie | Ticker | Lane | Uso potencial |
|---|---|---|---|
| S&P 500 | `^GSPC` | Core | Retorno, tendencia, drawdown y volatilidad realizada |
| VIX | `^VIX` | Core | Nivel y cambio de volatilidad implícita |
| SKEW | `^SKEW` | Core | Precio relativo del riesgo de cola |
| VIX9D | `^VIX9D` | Augmented | Estrés implícito de muy corto plazo |
| VIX3M | `^VIX3M` | Augmented | Estructura temporal de volatilidad |
| VVIX | `^VVIX` | Augmented | Volatilidad de la volatilidad |

### Lanes

- **Core:** SPX, VIX y SKEW. Busca conservar la historia diaria más extensa.
- **Augmented:** Core más VIX9D, VIX3M y VVIX. Aporta mayor riqueza, pero comienza más tarde y puede tener menor disponibilidad.

No se hace un `dropna` global. La falta de una serie Augmented no destruye la historia del Core.

### Input

- Fecha inicial inclusiva.
- Fecha final exclusiva.
- Directorio de salida.

Ejemplo:

```bash
python spx-flow-machine/src/yahoo_daily_adapter.py \
  --start 2010-01-01 \
  --end 2026-09-17 \
  --output-dir spx-flow-machine/data/daily_regime
```

### Output actual

- `canonical_daily.csv`: tabla diaria alineada con los cierres de las seis series.
- `raw/*.csv`: payload preservado por ticker.
- `coverage_report.json`: cobertura, inception, missingness y gaps potenciales.
- `metadata_manifest.json`: fuente, ticker, rango solicitado, timestamp y checksums.
- `snapshots/<snapshot_id>/`: copia inmutable identificada por el contenido raw y canónico.

### Validaciones implementadas

- Orden cronológico.
- Fechas duplicadas y observaciones conflictivas.
- Missingness explícita.
- Alineación por outer join.
- Fecha inicial y final efectiva por serie.
- Gaps potenciales entre weekdays.
- Valores no numéricos, infinitos o no positivos.
- Movimientos extremos como warning de plausibilidad.
- Checksums SHA-256 y provenance.

### Estado operativo

- La implementación pasa **10/10 tests offline**.
- No existe todavía en el workspace un snapshot persistido de una descarga real completa.
- La corrida real conocida falló explícitamente porque Yahoo no devolvió `^VIX9D` para el rango probado.
- Por eso la implementación está validada, pero Gate 1 todavía no debería congelarse como dataset real definitivo.

---

## 3. Datos sintéticos existentes

El dashboard Streamlit genera internamente:

- una trayectoria intradía sintética del SPX;
- trades sintéticos de opciones;
- strikes, vencimientos, cantidades y griegas aproximadas;
- clasificación heurística de calls/puts y compras/ventas;
- barras y features de flujo;
- un score direccional;
- retornos forward de 5 y 15 minutos;
- métricas descriptivas y gráficos.

### Qué produce

- Visualizaciones de precio y options flow.
- Distribuciones del score.
- Métricas 5m/15m.
- Una demostración end-to-end de interfaz y procesamiento.

### Limitaciones

- No contiene trades, quotes, bid/ask ni NBBO reales.
- No tiene acceso a Databento, OPRA u ORATS.
- El generador sintético introduce una relación con retornos futuros por diseño.
- Sus métricas no constituyen un backtest válido ni evidencia de alpha.
- No debe mezclarse con el research diario real.

---

## 4. Qué no producimos todavía con datos reales

La línea Yahoo todavía no genera:

- `risk-on` / `risk-off`;
- estados o probabilidades de régimen;
- transición entre estados;
- señales de entrada o salida;
- sizing;
- política de trading;
- evaluación out-of-sample;
- backtest.

Hoy produce datos diarios auditables, no interpretación económica.

---

## 5. Propuestas para generar market states con datos reales

### Propuesta A — Estados transparentes y determinísticos

**Recomendada como primer baseline.**

Construir features causales, calculadas sólo con información disponible hasta cada fecha:

- retornos SPX de 1, 5, 20 y 60 días;
- tendencia respecto de medias móviles;
- drawdown desde máximos;
- volatilidad realizada de 10, 20 y 60 días;
- nivel, cambio y percentil rolling de VIX;
- VIX9D/VIX y VIX/VIX3M;
- nivel y cambio de VVIX;
- nivel y cambio de SKEW.

Luego asignar estados con reglas simples y auditables, por ejemplo:

1. **Risk-on / calm:** tendencia positiva, drawdown reducido, VIX y volatilidad realizada bajos.
2. **Risk-on / fragile:** tendencia positiva, pero VIX, VVIX, SKEW o term structure muestran deterioro.
3. **Risk-off / stress:** tendencia negativa o drawdown relevante, VIX alto y term structure invertida.
4. **Recovery / transition:** mejora desde stress, pero con volatilidad todavía elevada.

Ventajas:

- Fácil de explicar y depurar.
- Menor riesgo de overfitting.
- Permite validar rápidamente si los estados tienen utilidad.

Riesgo:

- Los thresholds pueden ser arbitrarios. Deben fijarse con percentiles rolling o sólo en training data.

### Propuesta B — Modelo no supervisado

Usar HMM, Gaussian Mixture o clustering sobre las features reales.

Condiciones necesarias:

- estandarización rolling o estimada sólo en training;
- entrenamiento expanding o walk-forward;
- número pequeño de estados;
- nombres económicos asignados después de observar las características de cada cluster;
- control de estabilidad y persistencia temporal.

Ventajas:

- Puede descubrir combinaciones no evidentes.
- Produce probabilidades de estado.

Riesgos:

- Estados inestables entre reentrenamientos.
- Etiquetas difíciles de interpretar.
- Alta sensibilidad a escala, features y período de entrenamiento.

Debe ser un challenger del baseline transparente, no el primer sistema.

### Propuesta C — Riesgo futuro supervisado

Definir eventos futuros únicamente como targets de entrenamiento:

- drawdown SPX en los próximos 5/10/20 días;
- salto futuro de VIX;
- retorno futuro negativo extremo;
- entrada en un período de volatilidad elevada.

Entrenar un modelo sencillo, inicialmente logistic regression, para producir:

- probabilidad de stress futuro;
- probabilidad de transición;
- confianza/calibración.

Ventajas:

- Está directamente alineado con una decisión de riesgo.
- Produce probabilidades utilizables para exposición y sizing.

Riesgos:

- Mayor riesgo de leakage y overfitting.
- Requiere purging/embargo, walk-forward y calibración estricta.
- El target debe definirse antes de optimizar.

No debería comenzar hasta tener un baseline descriptivo estable.

---

## 6. Diseño recomendado

Mantener dos modelos separados:

### Modelo Core

Usa SPX, VIX y SKEW. Debe cubrir la historia más larga posible y ser el modelo principal.

### Modelo Augmented

Agrega VIX9D, VIX3M y VVIX. Funciona como challenger para el período donde todas las series están disponibles.

No conviene recortar el Core al inception de las variables Augmented.

### Output diario recomendado

```text
date
data_lane
market_state
state_probability
stress_probability
confidence
state_duration_days
transition_flag
primary_drivers
data_quality_flag
data_snapshot_id
model_version
```

Un output usable para trading debe incluir estado, probabilidad, confianza, drivers y trazabilidad al snapshot de datos.

---

## 7. Criterios mínimos para afirmar que un régimen es usable

- Todas las features son as-of y no contienen datos futuros.
- Thresholds, escalas y parámetros se estiman sólo en training.
- Evaluación expanding o walk-forward.
- Separación temporal estricta entre training y test.
- Resultados estables en diferentes períodos.
- Persistencia suficiente para evitar turnover excesivo.
- Comparación contra benchmarks simples.
- Costos y latencia incorporados cuando se traduzca a una política.
- Métricas por estado: retorno, volatilidad, drawdown, hit rate y duración.
- La utilidad debe existir fuera de muestra, no sólo en clasificación retrospectiva.

---

## 8. Secuencia sugerida

1. **Congelar Gate 1:** lograr una descarga Yahoo completa, revisar coverage y guardar el snapshot real.
2. **Gate 2:** construir features causales Core y Augmented, sin modelos.
3. **Gate 3:** implementar el baseline transparente de cuatro estados.
4. **Gate 4:** hacer evaluación walk-forward y decidir si los estados son utilizables.
5. **Gate 5:** comparar HMM/clustering y logistic regression como challengers.
6. Recién después traducir probabilidades de régimen a reglas de exposición o trading.

## Recomendación final

Empezar con la **Propuesta A**, usando dos lanes y cuatro estados interpretables. Validar primero si separan períodos con perfiles distintos de retorno, volatilidad y drawdown. Sólo si ese baseline aporta información fuera de muestra, avanzar a modelos probabilísticos más complejos.
