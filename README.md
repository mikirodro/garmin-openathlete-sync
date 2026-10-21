# Garmin → OpenAthlete Sync

Servicio Docker que descarga los FIT originales de Garmin Connect con `python-garminconnect` y los importa automáticamente en OpenAthlete. No requiere el conector oficial Garmin ni sus credenciales de desarrollador.

## Inicio

1. Copia `.env.example` a `.env` y completa las credenciales de ambas cuentas. La cuenta OpenAthlete debe tener perfil de atleta.
2. Arranca OpenAthlete y configura `OPENATHLETE_BASE_URL=http://api:3000`. El Compose comparte su red `openathlete_openathlete-network`; ajusta el nombre si tu despliegue usa otro. Consulta [DEPLOYMENT.md](DEPLOYMENT.md) para los requisitos y la operación. `localhost` dentro del contenedor apunta al propio contenedor.
3. Ejecuta:

```sh
docker compose build
docker compose run --rm garmin-openathlete-sync python -m app --login
docker compose run --rm garmin-openathlete-sync python -m app --once
docker compose up -d
docker compose logs -f
```

`--login` solicita MFA si Garmin lo requiere y conserva los tokens. La prueba `--once` importa realmente actividades; devuelve un código distinto de cero si algo falla. No inicialices simultáneamente varias instancias del servicio contra el mismo almacenamiento.

El servicio ejecuta un ciclo al arrancar y después espera 86400 segundos entre ciclos. No usa una hora fija del calendario. Para cambiar la frecuencia, configura `SYNC_INTERVAL_SECONDS`. Si Garmin vuelve a exigir MFA, repite `--login` con el servicio detenido y arráncalo después.

## Datos y reintentos

El montaje persistente `./data:/data` guarda tokens en `/data/garmin`, FIT y nombres en `/data/activities`, y el registro de importaciones en `/data/state.sqlite3`. `docker compose down` conserva esos archivos. En Linux, crea `data` antes de arrancar y permite escritura al usuario del contenedor: `mkdir -p data && sudo chown -R 10001:10001 data`. En Windows con Docker Desktop el montaje normalmente no requiere este ajuste.

Se recorren todas las páginas de actividades, desde las más recientes hasta `GARMIN_ACTIVITY_LOOKBACK_DAYS` días atrás (7 por defecto). `GARMIN_ACTIVITY_LIMIT` es el tamaño de página, no el máximo de actividades. Aumenta el lookback para la primera importación histórica. Los fallos de descarga se reintentan mientras la actividad siga dentro de esa ventana; amplíala si una interrupción prolongada deja actividades fuera.

Los FIT descargados cuyo envío haya fallado se reintentan incluso fuera de la ventana. El estado solo se confirma cuando OpenAthlete devuelve `eventId` y no indica procesamiento pendiente. Si una respuesta se pierde, reenviar los mismos bytes recupera la actividad existente gracias a la deduplicación de OpenAthlete. Los FIT se conservan como archivo local. Las advertencias de datos incompletos se registran.

## Migración del antiguo servicio TCX

Se conserva el historial Git. La integración anterior usaba `/event/import-tcx`; esta versión usa `/activity-import/fit` con `file` y `name`. Requiere desplegar una versión de OpenAthlete que incluya ese endpoint.

Se conserva `.env` y el montaje `./data:/data`. La reinicialización establece `SYNC_INTERVAL_SECONDS=86400` sin cambiar las credenciales. El servicio sigue usando `state.sqlite3`, por lo que las actividades TCX registradas previamente se omiten; no borres su estado sin revisar posibles duplicados.

## Configuración

| Variable | Uso / valor por defecto |
|---|---|
| `GARMIN_EMAIL`, `GARMIN_PASSWORD` | Cuenta Garmin Connect |
| `OPENATHLETE_EMAIL`, `OPENATHLETE_PASSWORD` | Cuenta OpenAthlete |
| `GARMIN_PASSWORD_FILE`, `OPENATHLETE_PASSWORD_FILE` | Archivos de secretos; prevalecen sobre la contraseña en variable |
| `OPENATHLETE_BASE_URL` | URL raíz de la API, incluido `/api` si lo requiere el proxy |
| `SYNC_INTERVAL_SECONDS` | `86400` |
| `GARMIN_ACTIVITY_LIMIT` | `100`, tamaño de página |
| `GARMIN_ACTIVITY_LOOKBACK_DAYS` | `7` |
| `DATA_DIR` | `./data` en Python; `/data` en Docker |
| `TZ` | `Europe/Madrid` en el ejemplo; filtrado en UTC |

La dependencia usa servicios de Garmin Connect mediante tu cuenta; cambios de autenticación pueden exigir actualizarla. El proceso importa actividades, no sueño, HRV ni otras métricas diarias. OpenAthlete admite FIT de hasta 20 MB, 100000 registros y 1000 vueltas, y rechaza actividades multideporte. Una actividad diferente con la misma hora de inicio genera conflicto y se mantiene pendiente para revisión.

## Desarrollo

Python 3.12 o posterior:

```sh
python -m venv .venv
# Activa .venv según tu sistema.
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Para usar el checkout local de `python-garminconnect` durante desarrollo:

```sh
python -m pip install -e ../python-garminconnect
```

En ejecución local, exporta las variables del entorno; Python no carga `.env` automáticamente. Docker Compose sí lo carga. Las pruebas no contactan cuentas reales.
