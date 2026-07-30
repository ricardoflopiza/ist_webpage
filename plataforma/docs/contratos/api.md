# Contrato de la API

Base: `/api/v1`. Documentación viva en `/api/docs` (deshabilitada en producción).

## Convenciones

* Rutas de tenant: `/api/v1/o/{org_slug}/…`. El `/o/{slug}` activa el aislamiento.
* Autenticación: cookie de sesión `ist_clima_session` (HMAC, `httpOnly`, `SameSite=Lax`,
  `Secure` en producción, 8 h).
* Errores: `{"detail": "..."}`.
  * `401` sin sesión · `403` sin permiso · `404` recurso inexistente **o de otro tenant**
    (no se confirma la existencia de recursos ajenos) · `409` estado incompatible ·
    `422` validación · `429` rate limit.
* Paginación: `?limit=&offset=` → `{"items": [...], "total": n}`.
* Fechas ISO 8601. Montos en CLP enteros; `null` significa «Cotizar».

## Consumidores

| Consumidor | Uso |
|---|---|
| Interfaz de la plataforma | Dashboards de resultados, comentarios y pulsos (`fetch` desde `dashboard.js`). |
| Consultoras (uso interno) | Automatización de altas, cargas de nómina y generación de invitaciones. |
| Integraciones futuras de RR. HH. | `POST /o/{slug}/population/import` es el punto de entrada previsto. |

Cambiar la forma de `GET /o/{slug}/results/{id}` rompe `app/static/js/dashboard.js`:
ambos deben actualizarse en el mismo commit.

## Endpoints principales

### Plataforma
```
GET  /platform/overview                 indicadores de la consultora
GET  /platform/activity                 actividad reciente
POST /platform/leads                    solicitud pública (rate limit por IP)
GET  /platform/leads                    bandeja de solicitudes
GET  /organizations                     organizaciones visibles
POST /organizations                     crear tenant
GET  /audit                             bitácora global
GET  /services · POST /services · PATCH /services/{id}
GET  /benchmarks · POST /benchmarks/build · POST /benchmarks/{id}/publish
```

### Organización
```
GET   /o/{slug}                         ficha
PATCH /o/{slug}                         configuración (incluye umbral)
GET   /o/{slug}/me                      rol y permisos efectivos
GET   /o/{slug}/units · POST · PATCH · DELETE
GET   /o/{slug}/population · POST · POST /import
GET   /o/{slug}/segmentation-keys
GET   /o/{slug}/members · POST · PATCH
GET   /o/{slug}/audit
```

### Instrumentos
```
GET  /o/{slug}/surveys                          plantillas maestras y propias
POST /o/{slug}/surveys                          crear desde cero
POST /o/{slug}/surveys/{id}/duplicate           adaptar (conserva derived_from_id)
POST /o/{slug}/surveys/{id}/versions            nueva versión editable
GET  /o/{slug}/surveys/versions/{id}            estructura completa
GET  /o/{slug}/surveys/versions/{id}/preview    previsualización + problemas
POST /o/{slug}/surveys/versions/{id}/publish    congela la versión
POST /o/{slug}/surveys/modules|dimensions|questions   (sólo en borrador)
GET  /o/{slug}/surveys/bank · /scales
```

### Campañas y respuesta
```
GET  /o/{slug}/campaigns · POST · GET /{id} · PATCH /{id}
POST /o/{slug}/campaigns/{id}/status            transiciones validadas
POST /o/{slug}/campaigns/{id}/invitations       devuelve los enlaces UNA vez
POST /o/{slug}/campaigns/{id}/invitations/mark-sent
GET  /o/{slug}/campaigns/{id}/participation     disponible con la campaña abierta
GET  /o/{slug}/campaigns/{id}/access            código / QR
GET  /o/{slug}/pulses · POST · GET /{id}/comparison
```

Público (sin autenticación): `GET /e/{token}`, `GET /e/codigo/{code}`,
`GET|POST /responder/{id}...`, `GET /retomar`.

### Resultados
```
GET /o/{slug}/results/{id}                      + filtros de segmentación
GET /o/{slug}/results/{id}/summary              resumen ejecutivo
GET /o/{slug}/results/{id}/heatmap              mapa de calor por unidad
GET /o/{slug}/results/{id}/drivers              impulsores + matriz
GET /o/{slug}/results/{id}/dimension/{code}
POST /o/{slug}/results/{id}/snapshot
```

**Forma de la respuesta de resultados**

```jsonc
{
  "allowed": true,
  "threshold": 7,
  "n_responses": 115,
  "general_score": 57.9,
  "participation": {"invited": 150, "started": 121, "submitted": 115, "rate": 76.7},
  "dimensions": [{
    "code": "liderazgo", "name": "Liderazgo", "score": 57.5, "n": 115,
    "favorable_pct": 37.5, "neutral_pct": 28.1, "unfavorable_pct": 34.4,
    "sd": 12.8, "ci95": [55.2, 59.8], "polarization": 0.51,
    "distribution": {"favorable": 173, "neutral": 130, "desfavorable": 159},
    "items": [...], "best_item": {...}, "worst_item": {...},
    "delta": 2.1, "benchmark": 64.0, "benchmark_delta": -6.5
  }],
  "outcomes": [...],
  "indices": [{"key": "...", "score": 56.0, "is_hypothesis": true, "note": "..."}],
  "drivers": [{"outcome_code": "compromiso", "n": 115, "r2": 0.53,
               "drivers": [{"code": "...", "beta": 0.26, "r": 0.44, "vif": 2.2,
                            "strength": "factor asociado"}],
               "warnings": ["..."], "disclaimer": "..."}],
  "priority_matrix": {"pivot_x": 65.0, "pivot_y": 0.18, "points": [...], "note": "..."}
}
```

**Cuando el segmento no se puede mostrar** (200, no 403):

```json
{"allowed": false, "reason": "bajo_umbral", "threshold": 7,
 "message": "Segmento con menos de 7 respuestas. No se muestra para proteger la confidencialidad.",
 "note": "No se entregan datos de segmentos bajo el umbral de confidencialidad."}
```

Motivos posibles: `bajo_umbral`, `universo_pequeno`, `cruce_riesgoso`, `sin_permiso`,
`fuera_de_alcance`, `campania_abierta`.

### Comentarios, hallazgos, acciones y reportes
```
GET   /o/{slug}/comments/{campaign_id}          ?q=&theme=&only_sensitive=
GET   /o/{slug}/comments/{campaign_id}/themes
PATCH /o/{slug}/comments/{comment_id}
GET   /o/{slug}/findings · POST · PATCH /{id} · POST /{id}/validate
POST  /o/{slug}/findings/suggest/{campaign_id}
GET   /o/{slug}/action-plans · POST · GET /dashboard · GET /{id}
POST  /o/{slug}/action-plans/{id}/items · PATCH /action-plans/items/{id}
GET   /o/{slug}/reports/{id}/executive · /organizational · /team/{unit_id}
GET   /o/{slug}/reports/{id}/export.csv
POST  /o/{slug}/reports/{id}/generate
```

### Excepcional
```
POST /o/{slug}/responses/{id}/raw   403 salvo capacidad concedida expresamente;
                                    exige justificación ≥ 20 caracteres; se audita.
```
