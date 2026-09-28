# Garmin → OpenAthlete Sync

Docker service that imports Garmin Connect activities into a self-hosted OpenAthlete instance.

## Status
Initial implementation: Garmin activity summaries are created as OpenAthlete ACTIVITY events and the original TCX is retained locally for the next full-data import phase.

## Run
Copy .env.example to .env, adjust OPENATHLETE_BASE_URL to the API address reachable from this container, then:

    docker compose up -d --build
    docker compose logs -f

The service has no inbound port. Garmin tokens, sync state and downloaded activity files live under ./data and are ignored by Git.

## Configuration
Required: GARMIN_EMAIL, GARMIN_PASSWORD (or GARMIN_PASSWORD_FILE), OPENATHLETE_BASE_URL, OPENATHLETE_EMAIL, OPENATHLETE_PASSWORD (or OPENATHLETE_PASSWORD_FILE).

Optional: SYNC_INTERVAL_SECONDS (900), GARMIN_ACTIVITY_LIMIT (20), GARMIN_ACTIVITY_LOOKBACK_DAYS (7), DATA_DIR (/data), TZ (Europe/Madrid).

Garmin authentication can require MFA on first login. python-garminconnect persists its token store, so subsequent cycles normally reuse/refresh it.

## Architecture
Garmin Connect → python-garminconnect → local SQLite idempotency state → OpenAthlete REST API.
