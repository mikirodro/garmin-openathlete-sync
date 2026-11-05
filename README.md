# Garmin → OpenAthlete Sync

Servicio Docker que importa automáticamente actividades FIT, métricas diarias de salud y entrenamientos programados de Garmin Connect en OpenAthlete mediante `python-garminconnect`. No requiere el conector oficial Garmin ni sus credenciales de desarrollador.

> [!WARNING]
> **Proyecto no oficial.** No está afiliado, patrocinado ni respaldado por Garmin Ltd. ni por OpenAthlete. "Garmin" y "Garmin Connect" son marcas de sus respectivos titulares y se citan solo para describir la compatibilidad.
>
> - Usa la API **no documentada** de Garmin Connect a través de [`python-garminconnect`](https://github.com/cyberjunky/python-garminconnect). Su uso puede no estar permitido por los términos de servicio de Garmin, puede dejar de funcionar sin aviso y Garmin podría limitar o bloquear tu cuenta. Úsalo solo con **tu propia cuenta** y bajo tu responsabilidad.
> - Maneja credenciales y **datos de salud y ubicación** (categoría especial de datos según el RGPD). Ejecútalo solo en infraestructura que controles, no lo despliegues para terceros sin su consentimiento y protege `.env` y `data/`.
> - Se distribuye "tal cual", sin garantías (ver [LICENSE](LICENSE)). No es un dispositivo médico.

## Inicio

1. Copia `.env.example` a `.env` y completa las credenciales de ambas cuentas. La cuenta OpenAthlete debe tener perfil de atleta.
2. Arranca OpenAthlete y configura `OPENATHLETE_BASE_URL=http://api:3000` y `ALLOW_INSECURE_HTTP=true` únicamente si confías en esa red local Docker. Para conexiones remotas usa HTTPS; es obligatorio por defecto. El Compose comparte su red `openathlete_openathlete-network`; ajusta el nombre si tu despliegue usa otro. Consulta [DEPLOYMENT.md](DEPLOYMENT.md) para los requisitos y la operación. `localhost` dentro del contenedor apunta al propio contenedor.
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

Los FIT descargados cuyo envío haya fallado se reintentan incluso fuera de la ventana. El estado solo se confirma cuando OpenAthlete devuelve `eventId` y no indica procesamiento pendiente. Si una respuesta se pierde, reenviar los mismos bytes recupera la actividad existente gracias a la deduplicación de OpenAthlete. Los FIT se conservan como archivo local. Las advertencias de datos incompletos se registran. Los archivos que OpenAthlete rechaza de forma definitiva (duplicados, multideporte, FIT inválido) se apartan a `/data/activities/rejected/` y no hacen fallar el ciclo; consulta [DEPLOYMENT.md](DEPLOYMENT.md#fit-rechazados-por-openathlete).

## Migración del antiguo servicio TCX

Se conserva el historial Git. La integración anterior usaba `/event/import-tcx`; esta versión usa `/activity-import/fit` con `file` y `name`. Requiere desplegar una versión de OpenAthlete que incluya ese endpoint.

Se conserva `.env` y el montaje `./data:/data`. La reinicialización establece `SYNC_INTERVAL_SECONDS=86400` sin cambiar las credenciales. El servicio sigue usando `state.sqlite3`, por lo que las actividades TCX registradas previamente se omiten; no borres su estado sin revisar posibles duplicados.

## Configuración

| Variable | Uso / valor por defecto |
|---|---|
| `GARMIN_EMAIL`, `GARMIN_PASSWORD` | Cuenta Garmin Connect |
| `OPENATHLETE_EMAIL`, `OPENATHLETE_PASSWORD` | Cuenta OpenAthlete |
| `GARMIN_PASSWORD_FILE`, `OPENATHLETE_PASSWORD_FILE` | Archivos de secretos; prevalecen sobre la contraseña en variable |
| `OPENATHLETE_BASE_URL` | Obligatoria: URL final de la API, incluido `/api` si lo requiere el proxy; no se siguen redirecciones |
| `ALLOW_INSECURE_HTTP` | `false`; `true` solo para permitir HTTP en una red local confiable |
| `SYNC_INTERVAL_SECONDS` | `86400` |
| `GARMIN_ACTIVITY_LIMIT` | `100`, tamaño de página |
| `GARMIN_ACTIVITY_LOOKBACK_DAYS` | `7` |
| `GARMIN_HEALTH_LOOKBACK_DAYS` | `7` días completos anteriores; Health añade hoy en cada ciclo |
| `GARMIN_PLANNED_DAYS` | `90` días desde hoy; máximo `366` |
| `DATA_DIR` | `./data` en Python; `/data` en Docker |
| `TZ` | `Europe/Madrid`; calendario local para salud y filtrado UTC para actividades |

La dependencia usa servicios de Garmin Connect mediante tu cuenta; cambios de autenticación pueden exigir actualizarla. El proceso importa actividades y métricas de salud diarias. OpenAthlete admite FIT de hasta 20 MB, 100000 registros y 1000 vueltas, y rechaza actividades multideporte. Una actividad diferente con la misma hora de inicio genera conflicto y se mantiene pendiente para revisión.

## Esfuerzo percibido (RPE)

Cada ciclo normal sincroniza la autoevaluación `summaryDTO.directWorkoutRpe`
de las actividades Garmin ya vinculadas a eventos OpenAthlete por SQLite.
Se convierte la escala Garmin 0..100 a la escala OpenAthlete 0..1, incluyendo
cero. Los valores ausentes no borran el RPE existente; los inválidos se rechazan.
Solo se actualizan eventos de tipo `ACTIVITY` y se verifica el resultado del PATCH.

Un RPE ya existente no se reclama como propio, aunque coincida con Garmin.
Las modificaciones y borrados manuales de un RPE importado se protegen con un
bloqueo persistente por actividad/evento: no se vuelven a sobrescribir. No hay
un comando automático para eliminar esa protección. El historial de escrituras,
comprobaciones y protecciones se guarda en tablas adicionales del SQLite existente.

Además de la ventana de actividades recientes, cada ciclo revisa hasta 20
candidatos antiguos, priorizando los menos recientemente comprobados. Para
recorrer el histórico aún no comprobado, con el servicio detenido:

```sh
docker compose stop garmin-openathlete-sync
docker compose run --rm garmin-openathlete-sync python -m app --rpe-backfill
docker compose up -d
```

El backfill solo procesa actividades con correspondencia en SQLite que todavía
no se hayan comprobado; no vuelve a recorrer las completadas al reanudar. Las
actividades sin RPE se consideran comprobadas y pueden revisarse después por la
rotación periódica. Ante limitación 429 se interrumpe el escaneo y los pendientes
siguen disponibles para otro intento. El fallo de RPE no impide las demás fases,
pero el ciclo informa de error. `--health-only`, `--performance-only` y
`--planned-only` no ejecutan RPE.

## Salud diaria

Cada ciclo sincroniza hoy y los últimos `GARMIN_HEALTH_LOOKBACK_DAYS` días completos (7 por defecto), según `TZ` (`Europe/Madrid` por defecto). Las métricas de hoy son provisionales y se actualizan en cada ciclo con los datos disponibles; la frecuencia depende de `SYNC_INTERVAL_SECONDS`, no es tiempo real. Garmin aporta la fecha local de cada registro; el sueño y HRV usan su fecha de resumen nocturno. `--health-days N` conserva N días completos anteriores y añade hoy para salud; la fase FTP mantiene únicamente los N días completos.

Incluye pulso en reposo, mínimo, máximo y media de muestras válidas; HRV nocturna y máximo de 5 minutos; peso, IMC, grasa, agua, músculo y hueso; sueño, fases, siestas y puntuación; estrés, carga/descarga de Body Battery, SpO₂, media diaria de muestras válidas de respiración, pasos, calorías, distancia y minutos activos. Solo se crean valores disponibles: ausencia o valores negativos de Garmin no se convierten en cero. OpenAthlete v1.2.0 rechaza valores cero en POST: los nuevos se omiten y cuentan como `zero_not_supported`, sin inventar valores positivos. Los registros propios existentes sí pueden actualizarse a cero mediante PATCH.

Para varias mediciones de peso/composición en una fecha se usa la media aritmética por campo. La media de pulso usa las muestras positivas del día, excluyendo huecos. Los totales diarios, mínimos, máximos y resúmenes nocturnos mantienen su significado; no se mezclan con otras métricas. Se convierte gramos a kg, metros a km, sueño a horas y estrés/actividad a minutos.

Se usa `POST /metric` con actualización por atleta, tipo y fecha. Las notas identifican el origen `Garmin Connect daily sync v1`. Los registros existentes de otro origen se respetan y se cuentan como `preserved_manual`. Las reejecuciones omiten valores idénticos y actualizan los importados que hayan cambiado; no duplican entradas. Una consulta o envío fallidos no bloquean las otras métricas, pero el proceso termina con error para permitir reintento. El siguiente ciclo vuelve a consultar su ventana; amplíala si una incidencia supera esos días.

También se consulta `get_max_metrics(fecha)` para importar VO₂max de carrera
(`VO2MAX`, sección `generic` de Garmin) y ciclismo (`VO2MAX_CYCLING`) por separado,
en ml/kg/min, sin conversiones. Se prefiere `vo2MaxPreciseValue` y, si no es válido,
se utiliza `vo2MaxValue`. Solo se importan estimaciones positivas y finitas cuya
`calendarDate` coincida con el día consultado: no se arrastra la última estimación
a días sin medición ni se mezclan las dos disciplinas. No todos los días o
dispositivos aportan estas métricas. Se aplican los mismos controles de protección
manual, actualización e idempotencia del resto de salud. Una consulta o estructura
de respuesta inesperada se registra como fallo sin sobrescribir valores anteriores
ni impedir el envío de las demás métricas. Se requiere que OpenAthlete admita ambos
tipos (confirmados en la API desplegada). Añade una consulta Garmin por día;
`--health-only --health-days N` incluye VO₂max en la ventana histórica solicitada.

## FTP y otras métricas de rendimiento

Cada ciclo sincroniza también el historial diario de FTP mediante
`get_functional_threshold_power_range`, manteniendo carrera y ciclismo separados.
Se utiliza la ventana `GARMIN_HEALTH_LOOKBACK_DAYS` y solo días completos;
a diferencia de salud, FTP no incluye hoy. Las peticiones históricas se dividen en intervalos de hasta 366 días,
que es el límite de Garmin. Se conserva la fecha de medición `updatedDate` cuando
coincide con el día de la serie, sin arrastrar valores antiguos a días sin datos.

`FTP_CYCLING` se guarda en W. OpenAthlete presenta `FTP_RUNNING` en W/kg: los W de
Garmin se dividen por el peso del mismo día (media de pesos Garmin, o una métrica
`WEIGHT` existente en OpenAthlete si no hay peso Garmin). No se usa el peso actual
para normalizar datos antiguos. Si falta un peso válido del mismo día, se omite
esa medición y se cuenta como `missing_running_weight`. Algunas cuentas no tienen
historial de FTP de carrera; una respuesta vacía no es un error.

Se conservan las mismas reglas de origen, protección manual, actualización e
idempotencia de las métricas de salud. Los fallos de una disciplina o bloque se
registran y no impiden importar los demás. El informe sin valores personales se
guarda en `/data/performance/last-report.json`. `--health-only` incluye la fase de
FTP; para importar únicamente FTP sin actividades, sueño ni entrenamientos:

```sh
# Con el servicio periódico detenido para evitar ejecuciones simultáneas:
docker compose run --rm garmin-openathlete-sync python -m app --performance-only --health-days 3650
```

La VAM de OpenAthlete (`VMA`, km/h) es velocidad aeróbica máxima. Las fuentes
Garmin consultadas no aportan una VAM directa ni potencia crítica de carrera o
ciclismo (`CRITICAL_POWER_RUNNING` / `CRITICAL_POWER_CYCLING`). Por eso el
importador no crea esos tres tipos: el ritmo de umbral de lactato no es VAM,
FTP no es potencia crítica, y VO₂max no permite deducir una VAM personal sin un
modelo y supuestos adicionales. No se rellenan esos campos mediante equivalencias
o estimaciones no solicitadas. Los tipos sin fuente se enumeran en el informe.

Referencia Garmin: [FTP y TP por deporte](https://support.garmin.com/it-IT/?faq=xfzTjFVyStA0wdo2wFLFOA).

Primera carga de 30 días, sin volver a importar actividades:

```sh
docker compose stop garmin-openathlete-sync
docker compose run --rm garmin-openathlete-sync python -m app --health-only --health-days 30
docker compose up -d
```

El informe sin valores de salud se guarda en `/data/health/last-report.json`. No se archivan las muestras completas de pulso. Para repetir una carga parcial utiliza el mismo comando y ventana. Las respuestas HTTP 429 de OpenAthlete se reintentan respetando `Retry-After` (hasta 6 reintentos por petición). Se requiere una versión de OpenAthlete con `/metric` y los tipos correspondientes (validado con v1.2.0).

## Entrenamientos programados

Cada ciclo importa el calendario de Garmin desde hoy hasta `GARMIN_PLANNED_DAYS` días, incluidos bloques, repeticiones, descansos LAP, objetivos de ritmo (m/s), pulso, potencia, cadencia y cargas de fuerza (kg). Se conservan notas y nombres de ejercicios. Las fechas usan `TZ` y su cambio de horario; los objetivos de distancia usan metros y los tiempos segundos. Si Garmin no indica hora se usa el comienzo del día local, sin inventar una duración para sesiones abiertas o por repeticiones.

Los meses consecutivos pueden repetir una sesión: se identifica por su ID de calendario, no por nombre ni por plantilla, de modo que una misma plantilla programada dos veces se importa dos veces. La relación con el evento de OpenAthlete y las huellas del contenido se guardan en la tabla `synced_workout` del SQLite existente, sin alterar el registro de actividades.

Los cambios de Garmin actualizan la sesión correspondiente si mantiene su ID de calendario. Se respetan ediciones, eliminaciones realizadas en OpenAthlete y sesiones vinculadas a una actividad completada. Una referencia en la descripción permite recuperar una creación cuya respuesta se perdió sin duplicarla. No se borran automáticamente sesiones que desaparezcan de Garmin; una cancelación o reprogramación con ID nuevo requiere revisar la copia anterior en OpenAthlete.

Las repeticiones anidadas se expanden conservando las series porque OpenAthlete admite un nivel; se respeta la omisión del último descanso. Los objetivos/condiciones no representables se conservan en notas y se enumeran en el informe. Los entrenamientos con segmentos de distintos deportes o repeticiones no soportadas se notifican como error y no se importan parcialmente. Los planes adaptativos solo aportan las sesiones que Garmin exponga en su calendario.

Carga o comprobación manual, con el servicio detenido para no ejecutar dos importadores sobre el mismo SQLite:

```sh
docker compose stop garmin-openathlete-sync
docker compose run --rm garmin-openathlete-sync python -m app --planned-only --planned-days 90
docker compose up -d
```

`--planned-only` no importa actividades ni salud. El informe se guarda en `/data/workouts/last-report.json`. Los fallos de una etapa no impiden ejecutar las demás; los límites HTTP 429 de OpenAthlete se reintentan respetando `Retry-After`.

Para importar sesiones planificadas de fechas pasadas, usa un intervalo inclusivo de hasta 366 días:

```sh
docker compose run --rm garmin-openathlete-sync python -m app --planned-only --planned-start 2026-09-21 --planned-end 2026-10-20
```

Detén antes el servicio y vuelve a arrancarlo al terminar, igual que en el ejemplo anterior. La carga histórica conserva los mismos controles de duplicados y ediciones manuales. Importa entrenamientos planificados como tales, sin crear actividades realizadas ni modificar las ya registradas. Garmin devuelve la definición actualmente disponible de cada entrenamiento; no garantiza recuperar versiones antiguas de plantillas editadas o borradas. El ciclo automático sigue mirando hacia el futuro.

## Versiones e imagen publicada

El proyecto sigue [Versionado Semántico](https://semver.org/lang/es/); los cambios
de cada versión están en [CHANGELOG.md](CHANGELOG.md) y en
[Releases](https://github.com/mikirodro/garmin-openathlete-sync/releases).
Para producción usa una versión etiquetada, no `main`.

Cada release publica una imagen multiarquitectura (amd64/arm64) con SBOM y
atestación de procedencia. Para usarla en lugar de compilar, sustituye en
`compose.yaml` la línea `build: .` por:

```yaml
    image: ghcr.io/mikirodro/garmin-openathlete-sync:1.2.0
```

Verifica que la imagen procede de este repositorio antes de desplegarla:

```sh
gh attestation verify oci://ghcr.io/mikirodro/garmin-openathlete-sync:1.2.0 --owner mikirodro
```

`python -m app --version` muestra la versión instalada.

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

## Seguridad y contribuciones

El programa restringe el acceso a DATA_DIR y crea archivos nuevos con umask 077.
Todos los modos mantienen un bloqueo exclusivo del directorio: detén el servicio
antes de un comando manual. El bloqueo se libera al terminar; no borres su archivo.
Se requiere Linux (Docker en Windows/macOS también ejecuta Linux).

Consulta [SECURITY.md](SECURITY.md) para credenciales y reportes privados,
[CONTRIBUTING.md](CONTRIBUTING.md) para forks y propuestas de cambios y
[LICENSE](LICENSE) para la licencia MIT.
