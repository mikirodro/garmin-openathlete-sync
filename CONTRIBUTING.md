# Contribuir

Usa Issues para errores y funcionalidades. Para cambiar código, crea un fork,
una rama y una pull request hacia `main`; no necesitas acceso de escritura.
Describe el problema, el comportamiento esperado y las pruebas realizadas.
Mantén las propuestas pequeñas y añade pruebas de regresión cuando corresponda.

Usa Python 3.12 y un entorno virtual. Instala `requirements-dev.txt` en tu entorno
de desarrollo y ejecuta `python -m pytest -q`. Las pruebas deben usar datos
sintéticos y dobles de clientes, sin acceder a cuentas reales ni a infraestructura ajena.
No ejecutes el importador para probar una PR contra datos de producción.

No adjuntes `.env`, tokens, FIT/GPX/TCX reales, SQLite, respuestas HTTP completas
ni logs sin anonimizar. Los archivos ignorados también pueden filtrarse con
`git add -f`: revisa siempre `git diff --cached` antes de hacer commit.

Las contribuciones se reciben bajo la licencia MIT del proyecto. Confirma que
tienes derecho a aportar el código y conserva los avisos de terceros.
Para vulnerabilidades, consulta SECURITY.md y evita los informes públicos.
