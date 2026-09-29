# Garmin → OpenAthlete Sync

Docker service that syncs Garmin activity summaries to a self-hosted OpenAthlete instance and stores downloaded TCX files locally.

## Status
This connector reads Garmin Connect with `python-garminconnect`, creates an OpenAthlete activity event with summary metadata, and retains the downloaded TCX under `./data/activities`.

Important: the OpenAthlete API exposed by the instance at `api:3000` has no endpoint for uploading an activity file or its data stream. `POST /event` creates only the activity event and does not upload the TCX or associate Garmin provider data. Therefore, this connector does not currently import complete activities into OpenAthlete. OpenAthlete's built-in Garmin integration is the supported way to import full activity data; it uses Garmin OAuth and needs Garmin developer credentials configured on the OpenAthlete server.

## Run
Copy `.env.example` to `.env`, then set your Garmin Connect and OpenAthlete account credentials. The OpenAthlete URL is preconfigured for `http://api:3000`; change it only if the API listens elsewhere. Then run:

    docker compose up -d --build
    docker compose logs -f

The service has no inbound port. Garmin tokens, sync state and downloaded activity files live under ./data and are ignored by Git.

## Configuration
Required: GARMIN_EMAIL, GARMIN_PASSWORD (or GARMIN_PASSWORD_FILE), OPENATHLETE_EMAIL, OPENATHLETE_PASSWORD (or OPENATHLETE_PASSWORD_FILE). OPENATHLETE_BASE_URL defaults to `http://api:3000`.

Optional: SYNC_INTERVAL_SECONDS (900), GARMIN_ACTIVITY_LIMIT (20), GARMIN_ACTIVITY_LOOKBACK_DAYS (7), DATA_DIR (/data), TZ (Europe/Madrid).

Garmin authentication can require MFA on first login. `python-garminconnect` persists its token store, so subsequent cycles normally reuse/refresh it. From the Docker container, the configured API URL must be reachable; this has been checked from the current host and the API's `/docs-json` responds.

## Architecture
Garmin Connect → python-garminconnect → local SQLite idempotency state → OpenAthlete REST API (activity summary only; TCX remains local).
