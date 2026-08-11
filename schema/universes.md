# Universes

Firebase path: `universes/{universeId}`

```json
{
  "active": true,
  "time": 491517.029,
  "time_updated_at_ms": 1786193922382.409,
  "objects": {},
  "spawn_config": {},
  "recent_projectile_outcomes": {}
}
```

## Universe fields

| Field | Type | Description |
| --- | --- | --- |
| `active` | boolean | Must be explicitly `true` for Flask and the UI to simulate/predict this universe. `false` or missing pauses it. |
| `time` | number | Authoritative simulation time in seconds at the last stored update. |
| `time_updated_at_ms` | number | Wall-clock timestamp in milliseconds used to analytically estimate continuous simulation time. |
| `objects` | map | Object ID → universe object. |
| `events` | map, optional | Short-lived authoritative action and outcome events (for example `PROJECTILE_FIRED`, `TRANSFER_SCHEDULED`, and confirmed combat events). |
| `recent_projectile_outcomes` | map, optional | Rolling backend record of recent projectile results. |
| `spawn_config` | map | Starter ship and gun settings captured when this generated universe was created. |

## Objects

Path: `universes/{universeId}/objects/{objectId}`

Every visible object normally has:

```json
{
  "type": "NATURAL | ARTIFICIAL",
  "owner": "username or null",
  "sub_type": "optional subtype",
  "life": 200,
  "max_life": 200,
  "border_radius": 2,
  "location": { "x": 0, "y": 0 }
}
```

### Natural object / star

```json
{
  "type": "NATURAL",
  "sub_type": "STAR",
  "life": 1000,
  "max_life": 1000,
  "location": { "x": 0, "y": 0 },
  "objects": {
    "radar_1": { "type": "RADAR", "radius": 150 }
  }
}
```

`sub_type` is optional for existing natural objects; `STAR` is the intended
subtype for generated stars.

## Generated universes

`POST /auth/universe/new` creates a random-ID universe with generated natural
stars. Its configuration is environment-driven:

| Variable | Default | Meaning |
| --- | ---: | --- |
| `UNIVERSE_STAR_COUNT` | `20` | Number of generated `NATURAL / STAR` objects. |
| `UNIVERSE_STAR_DISTANCE_TARGET` | `500` | Target average distance from a new star to its selected parent. |
| `UNIVERSE_STAR_DISTANCE_MIN` | `100` | Minimum allowed distance between any two stars. |
| `UNIVERSE_STAR_DISTANCE_MAX` | `2000` | Maximum distance from a new star to its selected parent. |
| `UNIVERSE_STAR_PLACEMENT_ATTEMPTS` | `100` | Candidate placements attempted before generation fails. |
| `UNIVERSE_STAR_LIFE` | `1000` | Initial life of each generated star. |
| `UNIVERSE_SHIP_LIFE` | `200` | Initial life of each generated starter ship. |
| `UNIVERSE_STAR_BORDER_RADIUS` | `2` | Default physical collision radius of each generated star. |
| `UNIVERSE_SHIP_BORDER_RADIUS` | `2` | Default physical collision radius of each generated starter ship. |

On a user's first entry, Flask atomically assigns an unowned natural star and
creates the requested number of owned `cruise_level_1` starter ships (maximum
`3`). The first player receives a random outer/corner star; later players are
assigned randomly from the five unowned stars farthest from already owned
stars. Each ship starts on a circular orbit around the assigned star and
receives one `GUN` using the captured default velocity and hit radius.
For `N` starter ships, their radii are evenly distributed from the centre to
`UNIVERSE_SHIP_ORBIT_RADIUS`: `base × 1/N` through `base × N/N`.

Top-level objects use `owner` to identify their user. Mounted objects inherit
their parent object's owner and do not store their own `owner` field.

`border_radius` defines physical contact. A client reports a predicted contact
to Flask, which reconstructs both positions and verifies only that pair. The
effective collision distance is the largest positive `border_radius` or
`hit_radius` on either object. Flask applies
`min(max(life1, blast_impact1), max(life2, blast_impact2))` damage to both and
deletes any object whose resulting life is zero.

### Artificial ship

```json
{
  "type": "ARTIFICIAL",
  "owner": "pilot_01",
  "sub_type": "cruise_level_1",
  "life": 200,
  "max_life": 200,
  "location": { "x": -80.76, "y": 77.59 },
  "curves": {},
  "objects": {
    "radar_1": { "type": "RADAR", "radius": 150 },
    "gun_1": { "type": "GUN", "velocity": 300, "hit_radius": 20 }
  }
}
```

### Projectile

Projectiles are artificial objects with `sub_type: "PROJECTILE"`.

```json
{
  "type": "ARTIFICIAL",
  "sub_type": "PROJECTILE",
  "life": 0,
  "max_life": 0,
  "blast_impact": 50,
  "source_objectid": "ship_1",
  "hit_radius": 20,
  "delete_at": 5010,
  "location": { "x": 10, "y": 20 },
  "curves": {
    "0": {
      "type": "STRAIGHT_LINE",
      "active": true,
      "start_location": { "x": 10, "y": 20 },
      "direction_vector": { "x": 1, "y": 0 },
      "velocity": 300,
      "valid_from": 5000,
      "valid_till": 5003.333
    }
  }
}
```

After `valid_till`, the UI hides the projectile. Flask retains it until
`delete_at` so historical hit verification remains possible.

`PROJECTILE_BLAST_IMPACT` (default `50`) sets the life deducted from a target
when Flask confirms the projectile hit. Life is clamped at `0`, and the
top-level target object is then deleted from Firebase (including its mounted
objects). A destroyed `STAR` is preserved instead with
`sub_type: "DEAD_STAR"` and `life: 0`.

## Curves

Path: `objects/{objectId}/curves/{curveId}`

### Orbital ellipse

```json
{
  "type": "ELLIPSE",
  "motion_type": "ORBIT",
  "active": true,
  "dotted": false,
  "focus1": "star_1",
  "major_axis": 112,
  "eccentricity": 0,
  "rotation": 0,
  "phase": 2.376,
  "phase_updated_at": 491517.029,
  "velocity": 20,
  "direction": 1,
  "valid_from": 115862.872,
  "valid_till": -1
}
```

| Field | Description |
| --- | --- |
| `focus1` | ID of the object at the first focus, normally a star. |
| `major_axis` | Semi-major axis / orbit radius for a circular orbit. |
| `eccentricity` | `0` for circular; between `0` and `<1` for an ellipse. |
| `rotation` | Major-axis rotation in degrees. |
| `phase` / `phase_updated_at` | Analytic movement reference point. |
| `velocity` | Linear speed along the curve in world units per simulation second. |
| `direction` | Movement direction sign; normally `1` or `-1`. |
| `valid_from` / `valid_till` | Curve availability window; `-1` means no end. |
| `dotted` | Planned/future curve rendering flag. |

### Straight-line projectile curve

`type: "STRAIGHT_LINE"` uses `start_location`, `direction_vector`, `velocity`,
`valid_from`, and `valid_till`. It does not use orbital fields such as `focus1`
or `phase`.

## Attached objects

Path: `objects/{objectId}/objects/{attachedObjectId}`

```json
{ "type": "RADAR", "radius": 150 }
```

```json
{ "type": "GUN", "velocity": 300, "hit_radius": 20 }
```

## Projectile events and outcomes

Confirmed hit event path:

```text
universes/{universeId}/events/{eventId}
```

```json
{
  "type": "PROJECTILE_HIT",
  "projectile_id": "projectile_abc",
  "target_id": "ship_2",
  "hit_time": 491479.394,
  "location": { "x": 123, "y": 456 }
}
```

Recent outcome path:

```text
universes/{universeId}/recent_projectile_outcomes/{projectileId}
```

```json
{ "status": "HIT", "target_id": "ship_2", "hit_time": 491479.394, "recorded_at": 491479.653 }
```

or:

```json
{ "status": "EXPIRED", "recorded_at": 491479.653 }
```
