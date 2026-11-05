# Despliegue junto a OpenAthlete

El servicio de sincronización comparte la red Docker de OpenAthlete y accede
directamente a su API mediante `http://api:3000`. No necesita publicar el puerto
de la API ni depender de la dirección IP del host.

## Preparación

1. Arranca el proyecto Docker Compose de OpenAthlete. Debe existir la red
   `openathlete_openathlete-network`; si tu despliegue usa otro nombre, ajusta
   `networks.openathlete.name` en `compose.yaml`.
2. Copia `.env.example` a `.env` y configura las credenciales.
3. En esta red Docker local, usa `OPENATHLETE_BASE_URL=http://api:3000` y
   `ALLOW_INSECURE_HTTP=true` si aceptas el transporte sin cifrar. Para otros
   destinos usa HTTPS. La URL debe ser definitiva: se rechazan redirecciones.
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

El contenedor se ejecuta como usuario sin privilegios (UID 10001), con sistema
de archivos de solo lectura salvo `/data` y `/tmp`, sin capacidades Linux,
con `no-new-privileges` y con rotación de logs. Si usas `*_PASSWORD_FILE`,
monta el secreto como volumen de solo lectura (`./secrets:/run/secrets:ro`).

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

El estado SQLite evita reenviar actividades ya importadas. Los FIT pendientes que aún no se han enviado se procesan incluso fuera de la ventana.
Los envíos con resultado incierto requieren revisión manual, como se indica abajo. No borres `data`: contiene los
tokens, los archivos originales y el historial de importaciones.

## Advertencias de importación

Las advertencias `FIT_INCOMPLETE_CHANNELS`, `FIT_MISSING_SUMMARY` o
`FIT_NO_STREAM` indican limitaciones en los datos del archivo importado.
Los FIT originales se conservan para revisión.

## FIT rechazados por OpenAthlete

Si OpenAthlete rechaza definitivamente un archivo (HTTP 400/409/413/422 con un
código de la API), el FIT y su nombre se mueven a `data/activities/rejected/`,
se registra el código en SQLite y el ciclo no lo cuenta como fallo ni lo vuelve
a descargar. Los errores de envío cuyo resultado no pueda confirmarse requieren revisión manual
antes de reintentar, incluidos errores 5xx, 429 o de red.

| Código | Causa | Qué hacer |
|---|---|---|
| `FIT_DUPLICATE_TIME` | Otra actividad del atleta empieza a la misma hora | Compara ambas en OpenAthlete; si sobra la existente, bórrala y reintenta |
| `FIT_MULTISPORT_UNSUPPORTED` | Actividad multideporte (triatlón, swimrun…) | OpenAthlete no la admite; consérvala archivada o regístrala a mano |
| `FIT_INVALID` | El archivo no se puede interpretar | Revisa la actividad en Garmin Connect; puede ser un registro dañado o sin datos |

Para reintentar los rechazados tras resolver la causa, con el servicio detenido:

    docker compose stop garmin-openathlete-sync
    docker compose run --rm garmin-openathlete-sync python -m app --retry-rejected
    docker compose run --rm garmin-openathlete-sync python -m app --once
    docker compose up -d

`--retry-rejected` no contacta con Garmin ni con OpenAthlete: solo devuelve los
archivos a la cola. Los que vuelvan a ser rechazados regresan a `rejected/`.

## Actualización de seguridad

Antes de actualizar, conserva una copia privada de código, configuración e imagen
anterior. Para el despliegue local HTTP existente, añade explícitamente
`ALLOW_INSECURE_HTTP=true` a `.env` antes de recrear el contenedor; no copies
`.env.example` sobre tus credenciales. Con HTTPS conserva el valor `false`.

Valida con `docker compose config --quiet` (sin volcar secretos), construye la
imagen y recrea únicamente este servicio. Comprueba su estado y el resultado
del ciclo normal; no ejecutes `--once` con el servicio activo. Las ejecuciones
manuales concurrentes se rechazan antes de contactar las cuentas.

Para revertir, restaura código/configuración y la imagen anterior y recrea solo
el importador. No borres SQLite ni los tokens; este cambio no migra su esquema.
La carpeta DATA_DIR pasa a 0700 y los nuevos archivos son privados. La reversión
no requiere ampliar esos permisos. No se modifican recursivamente archivos antiguos.

## Importaciones con resultado incierto

Antes de enviar un FIT se registra la intención en SQLite. Si se pierde la
respuesta, el proceso se interrumpe o la API confirma un evento sin ponerlo en
cola, el importador **no reenvía** ese FIT: exige una revisión manual y marca
el ciclo como fallido. Esto prioriza evitar duplicados; también puede requerir
una revisión cuando un fallo de red ocurrió antes de enviar el archivo.

Detén solo el importador y comprueba en OpenAthlete si el evento existe y está
procesado. Con un identificador de Garmin y de evento comprobados, enlázalos:

    docker compose stop garmin-openathlete-sync
    docker compose run --rm garmin-openathlete-sync python -m app --resolve-uncertain ID_GARMIN --event-id ID_EVENTO
    docker compose up -d garmin-openathlete-sync

Si has comprobado que no se creó ningún evento, omite `--event-id` para
permitir un reintento. Si sí existe pero no se procesó, resuelve primero el
procesamiento en OpenAthlete. No borres SQLite para desbloquear la importación.

## Supervisión y copias

`docker compose ps` refleja la salud del último ciclo completo: un error o una
marca de tiempo demasiado antigua hace que Docker marque el contenedor como
`unhealthy`. Configura Uptime Kuma para alertar sobre ese estado; este proyecto
no configura automáticamente monitores externos. El archivo privado
`data/cycle-status.json` conserva el último resultado y el último éxito.

Haz copias cifradas y de acceso restringido de `data` y `.env`, además de la
base de datos de OpenAthlete. Para una copia coherente de SQLite, detén el
importador o utiliza la API de copia de SQLite. Comprueba periódicamente la
restauración en un entorno aislado, sin conectar con las cuentas reales.

## Dependencias y compatibilidad

La imagen instala `requirements.lock` con versiones y hashes. Tras modificar
`requirements.txt`, regenera el lock con Python 3.12 y `pip-compile
--generate-hashes --output-file=requirements.lock requirements.txt`, revisa el
diff, audita las dependencias y ejecuta las pruebas antes de desplegar.

La API efectiva observada en esta instalación es OpenAthlete v1.4.0 y el
conector usa garminconnect 0.3.20. El ciclo existente terminó correctamente;
esto no sustituye pruebas de contrato con datos de prueba de cada endpoint.
No actualices OpenAthlete sin revisar sus migraciones y respaldar su base de
datos.
