# -*- coding: utf-8 -*-
"""API JSON versionada. Prefijo común: /api/v1.

Convenciones:
* Las rutas de una organización viven bajo `/api/v1/o/{org_slug}/…`; el
  middleware de tenancy usa ese `/o/{slug}` para activar el aislamiento.
* Errores: `{"detail": "..."}` con el código HTTP correspondiente.
* Paginación: `?limit=&offset=`; respuesta `{"items": [...], "total": n}`.
"""
API_PREFIX = "/api/v1"
