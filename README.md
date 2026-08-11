# Dark Forest simulation service

This Flask project is authoritative for validated actions and outcomes. The React UI remains a Firebase listener, but normal movement is calculated analytically from curves and a shared time anchor instead of receiving a location write every tick.

## Layout

- Flask starts outcome workers in background threads. Projectile hit/expiry processing remains server authoritative.
- `worker.py` remains available when you deliberately want a standalone worker process.
- `app.py` provides `GET /health` and `POST /simulation/tick` for health checks and local testing.
- `simulation/` contains Firebase-independent movement and ellipse math.
- `firebase/` contains the Admin SDK connection and Realtime Database reads/writes.

## Setup

```bash
cd /Users/nilarnabdebnath/Documents/dark_forests/dark_forest_flask
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set `FIREBASE_DATABASE_URL` in `.env`. For local development, set `FIREBASE_SERVICE_ACCOUNT_PATH` to the absolute path of a Firebase Admin SDK service-account JSON file. Do not commit that JSON file or `.env`.

`FIREBASE_HTTP_TIMEOUT_SECONDS=2` prevents a slow Firebase request from pausing the simulation for the Admin SDK's default 120 seconds.

## Run

Start Flask (this also starts the simulation worker):

```bash
python app.py
```

Do not also run `worker.py` in this deployment mode, or the universe would tick twice per second. Run one manual tick for testing only when `SIMULATION_ENABLED=false`:

```bash
curl -X POST http://localhost:5000/simulation/tick
```

## Required curve fields

```json
{
  "active": true,
  "focus1": "objectid1235",
  "major_axis": 200,
  "eccentricity": 0.8,
  "rotation": 30,
  "valid_till": -1,
  "velocity": 12,
  "direction": 1
}
```

`velocity` is normal world-distance per simulation second. `direction: 1` advances forward around the ellipse; `-1` advances backward (`0` is accepted as backward for compatibility). A curve's `phase` and `phase_updated_at` are its analytic reference point; clients advance from there on every rendered frame.

For a moving object, its `focus1` object must have a valid `location: { "x": ..., "y": ... }`. `universe/time` plus `time_updated_at_ms` form the shared clock. Flask checkpoints that pair when it accepts an action, and clients calculate the time between checkpoints. Set `SIMULATION_WRITE_POSITIONS=true` only to temporarily restore the legacy periodic location-writing worker.

## Tests

```bash
python -m unittest discover -s tests
```

## Interstellar transfer endpoint

Create a smooth elliptical transfer from `objectid1` to a circular orbit of radius `radnew` around `objectid2`:

```bash
curl -X POST http://localhost:5000/universes/univid1123/transfers \
  -H 'Content-Type: application/json' \
  -d '{"objectid1":"ship123","objectid2":"starB","radnew":500}'
```

The endpoint uses the ship's current active curve velocity and direction. It appends a scheduled `INTERSTELLAR_ELLIPSE` transfer curve and a scheduled circular destination curve, ending the old curve at `t1`. The response includes `t1`, `t2`, and the new curve IDs.
