# Seguridad

Las correcciones se orientan a la última versión de `main`. No se garantiza
soporte de versiones antiguas. Actualiza después de revisar los cambios.

No publiques vulnerabilidades, credenciales o datos de salud en Issues o PR.
Si está habilitado, usa Security → Report a vulnerability para informar en
privado. Si no está disponible, abre un issue sin detalles sensibles solicitando
un canal privado. El archivo SECURITY.md no habilita por sí solo esa función.

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
