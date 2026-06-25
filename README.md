# telearr

Telearr es una aplicacion en Python 3 que conecta Telegram con Sonarr y Radarr.

Funciones principales:

- Bot de Telegram para gestionar series (Sonarr) y peliculas (Radarr).
- Bot interactivo con botones para agregar cuando hay multiples resultados.
- Panel web admin en puerto `4545` con password.
- Aprobacion de clientes Telegram mediante token temporal (caduca en 30 min).
- Bloqueo/desbloqueo de clientes desde el panel.
- Registro de ultimas 30 busquedas y ultimas 30 actividades.
- Configuracion persistente en `data/config.yaml` editable desde el panel.

## Comandos del bot

Series:

- `/serie buscar <texto> [res=1080p] [audio=multi]`
- `/serie agregar <tvdbId> [res=1080p] [audio=multi]`
- `/serie estado <sonarrId>`
- `/serie borrar <sonarrId>`

Peliculas:

- `/pelicula buscar <texto> [res=1080p] [audio=multi]`
- `/pelicula agregar <tmdbId> [res=1080p] [audio=multi]`
- `/pelicula estado <radarrId>`
- `/pelicula borrar <radarrId>`

En `buscar`, el bot muestra botones para agregar directamente los resultados.

## Arquitectura

- API web: FastAPI
- Bot: `python-telegram-bot`
- Persistencia: SQLite (`data/telearr.db`)
- Config: YAML (`data/config.yaml`)

Flujo de configuracion:

1. Si no existe `data/config.yaml`, se crea con valores de variables de entorno.
2. Una vez creado, el panel administra el contenido del YAML.
3. El contenedor monta `./data` para persistir DB y configuracion.

## Variables de entorno

Usa `.env.example` como base para crear `.env`:

- `TELEGRAM_BOT_TOKEN`
- `SONARR_URL`
- `SONARR_API_TOKEN`
- `RADARR_URL`
- `RADARR_API_TOKEN`
- `ADMIN_PASSWORD`
- `SESSION_SECRET`
- `SERIES_ROOT_FOLDER`
- `MOVIES_ROOT_FOLDER`
- `SERIES_QUALITY_PROFILE_ID` (default: 1)
- `MOVIES_QUALITY_PROFILE_ID` (default: 1)
- `SERIES_DEFAULT_RESOLUTION` (default: 1080p)
- `SERIES_DEFAULT_AUDIO` (default: multi)
- `MOVIES_DEFAULT_RESOLUTION` (default: 1080p)
- `MOVIES_DEFAULT_AUDIO` (default: multi)

Adicionalmente se incluye `portainer.env.example` para usarlo en Portainer Stack.

## Configuracion avanzada de perfiles (YAML)

Puedes mapear `res|audio` a perfiles de calidad en `data/config.yaml`.

Ejemplo:

```yaml
defaults:
	series_quality_profile_id: 1
	movies_quality_profile_id: 1
	series_default_resolution: 1080p
	series_default_audio: multi
	movies_default_resolution: 1080p
	movies_default_audio: multi
	series_quality_profiles:
		1080p|multi: 4
		2160p|multi: 5
	movies_quality_profiles:
		1080p|multi: 3
		2160p|multi: 6
	series_language_profiles:
		multi: 1
		es: 2
```

Si no existe mapeo para `res|audio`, se usa `SERIES_QUALITY_PROFILE_ID` o `MOVIES_QUALITY_PROFILE_ID`.

## Ejecucion con Docker Compose

1. Copia variables:

	`cp .env.example .env`

2. Ajusta credenciales y rutas en `.env`.

3. Levanta el servicio:

	`docker compose up --build -d`

4. Abre panel admin:

	`http://localhost:4545`

## Notas de seguridad

- Cambia `ADMIN_PASSWORD` y `SESSION_SECRET` antes de produccion.
- El bot solo permite acciones a usuarios aprobados y no bloqueados.
- Los tokens de aprobacion expiran en 30 minutos.
