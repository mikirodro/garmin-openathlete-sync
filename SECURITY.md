# Seguridad

| Versión | Soporte de seguridad |
|---|---|
| Última release `1.x` | ✅ |
| Anteriores | ❌ |

Las correcciones se publican como nueva release (ver CHANGELOG.md). Actualiza
después de revisar los cambios y verifica la atestación de la imagen
(`gh attestation verify`), como se indica en el README.

No publiques vulnerabilidades, credenciales o datos de salud en Issues o PR.
Informa en privado desde Security → Report a vulnerability
(https://github.com/mikirodro/garmin-openathlete-sync/security/advisories/new).
Se intentará responder en un plazo de 7 días y coordinar la divulgación.

Incluye versiones afectadas, impacto y reproducción mínima con datos sintéticos.
Nunca pruebes contra cuentas, servicios o infraestructura de terceros.

El importador maneja contraseñas, tokens, salud y ubicaciones. Usa HTTPS para la
API; HTTP requiere `ALLOW_INSECURE_HTTP=true` y solo debe habilitarse cuando
aceptes expresamente el transporte sin cifrar en una red local confiable.
Las redirecciones de la API se rechazan: configura la URL final, con el prefijo
correcto. Usa archivos `_PASSWORD_FILE` montados de solo lectura cuando sea posible.

La CLI usa umask 077, restringe DATA_DIR a 0700 y mantiene un bloqueo exclusivo
por directorio durante toda la ejecución, incluida la espera entre ciclos.
Los archivos nuevos son privados; no reescribe recursivamente permisos de datos
antiguos. Protege también directorios padre, copias y el acceso al host/Docker.
El bloqueo usa flock y requiere Linux y almacenamiento con bloqueos fiables;
no coordina instancias que utilicen directorios distintos ni otros importadores.
No borres `.sync.lock`: el bloqueo se libera al terminar el proceso.
