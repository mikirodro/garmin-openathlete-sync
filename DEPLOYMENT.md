# Despliegue junto a OpenAthlete

El servicio de sincronización comparte la red Docker de OpenAthlete y accede
directamente a su API mediante `http://api:3000`. No necesita publicar el puerto
de la API ni depender de la dirección IP del host.

## Preparación

1. Arranca el proyecto Docker Compose de OpenAthlete. Debe existir la red
   `openathlete_openathlete-network`; si tu despliegue usa otro nombre, ajusta
   `networks.openathlete.name` en `compose.yaml`.
2. Copia `.env.example` a `.env` y configura las credenciales.
3. Usa `OPENATHLETE_BASE_URL=http://api:3000`.
4. Prepara los datos persistentes y protege las credenciales:

       mkdir -p data
       chown -R 10001:10001 data
       chmod 700 data
       chmod 600 .env

5. Construye la imagen, inicializa los tokens y ejecuta la primera sincronización:

       docker compose build
       docker compose run --rm garmin-openathlete-sync python -m app --login
       docker compose run --rm garmin-openathlete-sync python -m app --once
       docker compose up -d

## Operación

Consulta el estado y los registros:

    docker compose ps
    docker compose logs --tail 50

El servicio arranca un ciclo inmediatamente y repite cada
`SYNC_INTERVAL_SECONDS`. La política `unless-stopped` permite reiniciarlo
automáticamente tras reiniciar Docker, salvo que se haya detenido expresamente.

Para ampliar el histórico, ajusta `GARMIN_ACTIVITY_LOOKBACK_DAYS` en `.env` y
ejecuta una sincronización manual sin instancias simultáneas:

    docker compose stop
    docker compose run --rm garmin-openathlete-sync python -m app --once
    docker compose up -d

Ejecuta también `docker compose up -d` si la sincronización manual termina con
error, para reactivar el servicio. Revisa los registros para conocer los fallos.

El estado SQLite evita reenviar actividades ya importadas. Los FIT pendientes
se reintentan incluso fuera de la ventana. No borres `data`: contiene los
tokens, los archivos originales y el historial de importaciones.

## Advertencias de importación

Las advertencias `FIT_INCOMPLETE_CHANNELS`, `FIT_MISSING_SUMMARY` o
`FIT_NO_STREAM` indican limitaciones en los datos del archivo importado.
Los FIT originales se conservan para revisión.

`FIT_DUPLICATE_TIME` indica que otra actividad del mismo atleta empieza a la
misma hora. La API rechaza la importación y el archivo queda pendiente; revisa
ambas actividades antes de decidir cómo resolverlo.
