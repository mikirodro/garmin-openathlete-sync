# Changelog

Todos los cambios relevantes se documentan en este archivo.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).

## [Unreleased]

## [1.0.0] - 2026-11-04

Primera versión pública.

### Añadido
- Importación automática de actividades FIT originales de Garmin Connect en
  OpenAthlete mediante `/activity-import/fit`, con reintento de envíos fallidos.
- Sincronización diaria de métricas de salud (pulso, HRV, sueño, estrés,
  Body Battery, SpO₂, respiración, pasos, calorías y composición corporal),
  incluido el día en curso.
- VO₂max de carrera y ciclismo por día de medición.
- Historial de FTP de carrera (W/kg) y ciclismo (W).
- Sincronización del esfuerzo percibido (RPE) respetando ediciones manuales.
- Importación de entrenamientos programados con bloques, repeticiones y objetivos.
- Modos `--login`, `--once`, `--health-only`, `--performance-only`,
  `--rpe-backfill`, `--planned-only` y `--version`.
- Imagen de contenedor multiarquitectura (amd64/arm64) en GHCR con SBOM y
  atestación de procedencia de compilación.

### Seguridad
- HTTPS obligatorio salvo opt-in explícito, sin redirecciones ni credenciales en la URL.
- `DATA_DIR` privado (0700, umask 077) y bloqueo exclusivo entre instancias.
- Contenedor sin root, sistema de archivos de solo lectura, sin capacidades Linux
  y con `no-new-privileges`.
- Dependencias, imagen base y Actions fijadas; Dependabot y `pip-audit` en CI.

[Unreleased]: https://github.com/mikirodro/garmin-openathlete-sync/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/mikirodro/garmin-openathlete-sync/releases/tag/v1.0.0
