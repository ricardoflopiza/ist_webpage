# Plan de implementación y estado

## Etapas completadas

### Etapa 1 · Base ✅
Auditoría del repositorio, arquitectura, configuración por entorno, modelo de datos,
autenticación (PBKDF2 600k + cookie HMAC + rate limiting), multitenancy con guardas
centrales, matriz de permisos y sistema de diseño B2B.

### Etapa 2 · Organizaciones e instrumentos ✅
Organizaciones, estructura jerárquica, nómina con carga CSV, biblioteca de diez
instrumentos maestros, banco de preguntas, catálogo de escalas, adaptación con
trazabilidad y versionado inmutable al publicar.

### Etapa 3 · Campañas y aplicación ✅
Campañas con máquina de estados, población filtrable, invitaciones con token hasheado,
acceso por enlace/código/QR, experiencia de respuesta responsive con consentimiento,
guardado progresivo y retomado, separación total entre nómina y respuestas.

### Etapa 4 · Cálculo y resultados ✅
Motor de cálculo 0-100, favorabilidad, ítems invertidos, cobertura mínima, IC 95 %,
polarización, índices marcados como hipótesis, análisis de impulsores con advertencias,
matriz de prioridad, mapa de calor con supresión complementaria, dashboard con ECharts.

### Etapa 5 · Cualitativo y gestión ✅
Comentarios con ocultamiento de datos personales, detección y protocolo de menciones
sensibles, agrupación temática de apoyo, hallazgos sugeridos y validados, planes de acción
con evidencia obligatoria, tablero de seguimiento y pulsos comparados con línea base.

### Etapa 6 · Reportes, servicios, benchmarks y despliegue ✅
Reportes ejecutivo/organizacional/de equipo, exportación CSV auditada, catálogo de
servicios administrable, benchmarks con mínimos de anonimización, página pública
comercial, Docker Compose, CLI y documentación.

---

## Etapa 7 · Endurecimiento (pendiente, en orden de prioridad)

1. **Alembic.** Hoy el esquema se crea con `create_all`. Antes del primer cambio
   destructivo hay que incorporar migraciones versionadas. *Bloqueante para producción con
   datos reales.*
2. **Envío de correos.** Las invitaciones y recordatorios se entregan como enlaces; falta
   un proveedor. El envío debe leer el token del retorno de `generate_invitations`, nunca
   de la base (ahí sólo está el hash).
3. **Rate limiting en Redis.** El actual es en memoria: con varios workers cada uno cuenta
   por separado.
4. **Cabeceras de seguridad y CSRF.** CSP, `X-Frame-Options`, `Referrer-Policy` y token
   CSRF en los formularios HTML (la API por cookie ya usa `SameSite=Lax`).
5. **Backup automatizado y off-site** del Postgres de la plataforma.
6. **Reportes en PDF** (hoy web/JSON/CSV) y exportación a presentación.
7. **Cálculo asíncrono** para campañas de más de ~5.000 respuestas: mover `compute_payload`
   a una cola y servir siempre desde `ResultSnapshot`.
8. **Validación psicométrica de los índices**: alfa de Cronbach y análisis factorial sobre
   datos reales, para dejar de presentarlos como hipótesis.
9. **Modelos avanzados de impulsores**: multinivel (personas dentro de unidades), random
   forest / gradient boosting con SHAP y validación cruzada, comparando contra la
   regresión actual.
10. **Editor visual del instrumento.** Hoy la edición fina de preguntas es por API; la
    interfaz muestra estructura y previsualización.
11. **Resumen asistido por IA de comentarios**, con revisión humana obligatoria y sin
    tocar los marcados como sensibles.
12. **SSO (SAML/OIDC)** para el paquete Enterprise.
13. **Interfaz de administración de plataforma** (crear organizaciones, editar servicios y
    construir benchmarks se hace hoy por API).
14. **Accesibilidad**: auditoría WCAG AA completa sobre la encuesta y los dashboards.

## Riesgos

### Técnicos
* **Sin migraciones versionadas** (mitigación: etapa 7.1 antes de datos reales).
* **Cálculo síncrono**: con campañas muy grandes el request se alarga; hay snapshots como
  salida, pero el cálculo en vivo con filtros es CPU-bound.
* **Rate limiting por proceso**: falso sentido de protección con varios workers.
* **SQLite en desarrollo y PostgreSQL en producción**: los tests corren sobre SQLite; las
  diferencias de tipos JSON y de concurrencia podrían esconder problemas. Mitigación
  parcial: no se usa SQL específico de motor.

### Metodológicos
* **Índices agregados sin validar**: van marcados, pero un cliente puede tomarlos como
  constructos. Mitigación: advertencia visible y etapa 7.8.
* **Correlación leída como causalidad**: mitigado con vocabulario, advertencias y
  disclaimer en cada payload, pero el riesgo es de interpretación humana en la devolución.
* **Comparaciones entre equipos de tamaños muy distintos**: el umbral protege la identidad,
  no la validez de la comparación. La devolución debe explicitarlo.
* **Confusión con instrumentos regulatorios**: la plataforma declara explícitamente que no
  reemplaza CEAL-SM/SUSESO, en la web pública, en los reportes y en la aplicación.
* **Falsa sensación de anonimato en organizaciones muy pequeñas**: con 15 personas casi
  cualquier segmentación es identificable. El umbral bloquea, pero conviene acordar con el
  cliente qué se podrá reportar antes de aplicar.
