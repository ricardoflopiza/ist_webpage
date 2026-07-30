# Matriz de roles y permisos

Fuente de verdad: [`app/security/permissions.py`](../app/security/permissions.py). Los
permisos se verifican en la API; la interfaz sólo refleja la decisión.

| Capacidad | Superadmin | Consultor | Admin. cliente | Jefatura | Analista | Participante |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| Crear organizaciones | ✅ | — | — | — | — | — |
| Gestionar planes y usuarios globales | ✅ | — | — | — | — | — |
| Plantillas maestras | ✅ | — | — | — | — | — |
| Métricas de uso de la plataforma | ✅ | — | — | — | — | — |
| Benchmarks (administrar) | ✅ | — | — | — | — | — |
| Auditoría global | ✅ | — | — | — | — | — |
| Catálogo de servicios | ✅ | — | — | — | — | — |
| Consola de la consultora | ✅ | ✅ | — | — | — | — |
| Configurar la organización | ✅ | ✅ | — | — | — | — |
| Estructura y nómina | ✅ | ✅ | ✅ | — | — | — |
| Adaptar instrumentos / publicar versiones | ✅ | ✅ | — | — | — | — |
| Crear y gestionar campañas | ✅ | ✅ | ✅ | — | — | — |
| Publicar / cerrar campañas | ✅ | ✅ | — | — | — | — |
| Invitaciones | ✅ | ✅ | ✅ | — | — | — |
| Ver participación | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Resultados de toda la organización | ✅ | ✅ | ✅ | — | ✅ | — |
| Resultados de las unidades propias | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Análisis de impulsores | ✅ | ✅ | ✅ | — | ✅ | — |
| Comentarios abiertos | ✅ | ✅ | ✅ | — | ✅ | — |
| Comentarios sensibles (con protocolo) | ✅ | ✅ | — | — | — | — |
| Etiquetar / revisar comentarios | ✅ | ✅ | — | — | — | — |
| Registrar hallazgos | ✅ | ✅ | — | — | — | — |
| Validar hallazgos | ✅ | ✅ | — | — | — | — |
| Gestionar planes de acción | ✅ | ✅ | ✅ | — | — | — |
| Actualizar avance y evidencia | ✅ | ✅ | ✅ | ✅ | — | — |
| Crear pulsos | ✅ | ✅ | — | — | — | — |
| Ver reportes | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Generar reportes | ✅ | ✅ | — | — | — | — |
| Exportar datos | ✅ | ✅ | ✅ | — | — | — |
| Responder encuestas | — | — | — | — | — | ✅ |
| **Ver respuestas individuales** | **—** | **—** | **—** | **—** | **—** | **—** |

## Sobre la última fila

`response.raw.read` **no está en el conjunto de ningún rol**, tampoco en el del
superadministrador. El endpoint existe como función técnica excepcional
(`POST /api/v1/o/{slug}/responses/{id}/raw`): exige justificación escrita de al menos 20
caracteres, responde 403 salvo que la capacidad se otorgue de forma expresa y temporal, y
deja registro permanente marcado como `excepcional`. Aun concedido, lo que devuelve son
respuestas sin ninguna referencia a la persona: **la plataforma no guarda ese vínculo**.

## Alcance de una jefatura

Una membresía de jefatura requiere `scope_unit_ids` no vacío. Sus consultas de resultados:

* deben incluir `org_unit_id`, y ese identificador debe estar en su alcance;
* sin filtro de unidad reciben `fuera_de_alcance` (no ven el total de la organización);
* siguen sujetas al umbral: un equipo pequeño no se muestra ni a su propia jefatura.

## Superadministrador sin membresía

Puede entrar a cualquier organización por función técnica. Cada ingreso y cada consulta de
resultados quedan en la bitácora. No obtiene acceso a respuestas individuales.
