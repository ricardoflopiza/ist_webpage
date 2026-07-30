# istendencia · Plataforma de clima y experiencia organizacional

SaaS multitenant para que una consultora administre diagnósticos de clima laboral de
varias organizaciones: configurar el diagnóstico, adaptar el instrumento, aplicarlo de
forma anónima, seguir la participación, analizar, priorizar, convertir hallazgos en
planes de acción y verificar avances con encuestas pulso.

> **Alcance metodológico.** Mide clima y experiencia organizacional, y puede incorporar
> módulos sobre condiciones psicosociales. **No reemplaza los instrumentos regulatorios
> oficiales** (en Chile, CEAL-SM/SUSESO) ni entrega diagnósticos clínicos individuales:
> todos los resultados son organizacionales y grupales.

---

## Puesta en marcha local

```bash
cd plataforma
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env                     # editar SESSION_SECRET

# Base de datos, biblioteca de instrumentos y catálogo de servicios
SEED_DEMO=1 .venv/bin/python -m app.cli init-db

# Servidor de desarrollo
SEED_DEMO=1 .venv/bin/uvicorn app.main:app --reload --port 8003
```

* Página pública: <http://localhost:8003/>
* Aplicación: <http://localhost:8003/entrar>
* API (OpenAPI): <http://localhost:8003/api/docs> (sólo fuera de producción)

### Credenciales de la organización de demostración

Se crean sólo con `SEED_DEMO=1` y quedan marcadas como datos ficticios:

| Rol | Correo | Contraseña |
|---|---|---|
| Consultora | `consultora@istendencia.demo` | `demo1234` |
| Administración del cliente | `rrhh@andes.demo` | `demo1234` |
| Jefatura | `jefatura.operaciones@andes.demo` | `demo1234` |

**Nunca activar `SEED_DEMO` en producción.**

### Primer administrador real

```bash
.venv/bin/python -m app.cli crear-admin admin@istendencia.cl "Nombre Apellido"
.venv/bin/python -m app.cli crear-organizacion mi-cliente "Mi Cliente SpA"
```

No existe ninguna credencial por defecto: en producción, sin `ADMIN_EMAIL`/`ADMIN_PASSWORD`
o sin ejecutar `crear-admin`, no hay forma de entrar.

---

## Comandos

```bash
python -m app.cli init-db                       # esquema + biblioteca + servicios
python -m app.cli crear-admin <correo> "<nombre>"
python -m app.cli crear-organizacion <slug> "<nombre>"
python -m app.cli cargar-demo                   # organización de demostración
python -m app.cli reset-password <correo>       # contraseña temporal de un solo uso
```

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m pytest tests/ --cov=app --cov-report=term-missing
.venv/bin/ruff check app tests
```

Cubren cálculo (normalización, ítems invertidos, cobertura mínima, favorabilidad),
confidencialidad (umbrales, supresión complementaria, ocultamiento de datos personales),
aislamiento multitenant (intentos activos de acceso cruzado), permisos por rol y el flujo
crítico punta a punta.

---

## Despliegue

```bash
cp .env.example .env    # completar SESSION_SECRET, POSTGRES_*, PUBLIC_BASE_URL
docker compose up -d --build
docker compose exec clima-app python -m app.cli crear-admin admin@istendencia.cl "Admin"
```

El contenedor publica sólo en `127.0.0.1:8003`; la exposición pública se hace con el
proxy que ya opera la infraestructura (Caddy tras Cloudflare Tunnel). Health check en
`/health`.

**Actualización**

```bash
git pull && docker compose up -d --build   # el esquema se crea/actualiza al arrancar
```

**Rollback**

```bash
git checkout <commit-anterior> && docker compose up -d --build
```

Las migraciones destructivas no se aplican solas: `Base.metadata.create_all` sólo crea lo
que falta. Un cambio que borre o renombre columnas debe hacerse con una migración escrita
a mano y un respaldo previo.

**Respaldo**

```bash
docker compose exec clima-db pg_dump -U "$POSTGRES_USER" clima > backups/clima_$(date +%F).sql
```

---

## Variables de entorno

Todas documentadas en [.env.example](.env.example). Las obligatorias en producción son
`SESSION_SECRET`, `DATABASE_URL` y `PUBLIC_BASE_URL`. Ningún secreto se versiona.

---

## Documentación

| Documento | Contenido |
|---|---|
| [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md) | Diagrama, decisiones e invariantes globales |
| [docs/MODELO_DATOS.md](docs/MODELO_DATOS.md) | Entidades y relaciones |
| [docs/ROLES.md](docs/ROLES.md) | Matriz de roles y permisos |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Etapas, estado y pendientes |
| [docs/flujos/](docs/flujos/) | Recorridos punta a punta con sus invariantes |
| [docs/contratos/api.md](docs/contratos/api.md) | Contrato de la API |

---

## Estructura

```
app/
  config.py          configuración por entorno
  db.py              motor + guardas multitenant (do_orm_execute / before_flush)
  models/            entidades por dominio
  security/          contraseñas, sesiones, tokens, permisos, dependencias
  services/          escalas, cálculo, impulsores, anonimato, campañas, biblioteca
  api/               API JSON (/api/v1)
  web/               vistas HTML (pública, encuesta, aplicación)
  templates/ static/ interfaz
tests/               unitarios, de permisos, multitenant y punta a punta
docs/                arquitectura, flujos y contratos
```
