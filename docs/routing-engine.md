# The routing engine

The system runs its own routing engine, [GraphHopper](https://github.com/graphhopper/graphhopper)
11.1 (Apache 2.0), as the `routing` service of every Docker stack (production,
the laptop demo and the Windows home install). It gives:

- **travel times** between runs for the scheduler (empty driving, the drive
  out of the yard and back), and
- **turn-by-turn directions** on the driver's tablet, for runs and field trips,
  in English or Spanish,

for a school bus, not a car. It needs no account, no key and no internet
connection, and nothing about the district's routes leaves the server.

OpenRouteService (`ISD_API_ORS_API_KEY`) still works where there's no
routing engine; with neither, the scheduler uses straight-line estimates and
drivers get the stop order with a link to each stop in their maps app.

## What a request takes into account

Every request the API makes carries a *custom model* built for that bus
(`services/solver/src/isd_solver/graphhopper.py`):

| Spec | What | How |
|---|---|---|
| §6 | The bus's height, width, length and weight | Roads whose mapped limit it exceeds are closed to it |
| §6 | Roads a bus may use | The `school_bus` profile (`services/routing/custom_models/school_bus.json`): bus access, no private roads, destination-only roads avoided |
| §7 | Prefer right turns over lefts | Each turn adds seconds to the route's cost: right 5, sharp right 30, left 20, sharp left 60 (Setup → Rules & optimization → Turn costs) |
| §7 | Lefts across several lanes | A left onto or off a main road (trunk, primary, secondary) adds 60 more |
| §7 | U-turns | Never by reversing onto another road; turning back along the same road costs 120 s (the profile's `u_turn_costs`), so it's used only when there's no other way, as at the end of a dead end. Stops never make the bus turn round (`pass_through`) |
| §7 | Dead ends and approved turnarounds | The district records approved turnarounds (District knowledge → "approved turnaround") with the longest bus that can turn there. Directions warn the driver ("Check before you go") wherever the route turns round anywhere else, or at a turnaround too short for this bus or for a bus whose length isn't recorded |
| §8 | Flooding, invalid turnarounds, size-restricted zones | Closed to every bus, or to the buses that don't fit |
| §8 | Difficult intersections and unsafe turns | Costs, not closures: roads within about 40 m count as five times their time, so the route goes round unless that's much longer |
| §10 | Road closures in force | Closed |

Turn costs only choose the route: the times reported are driving times.
Turn restrictions in the map (no left turn, only straight on) apply too.

What the map can't say: whether an intersection has signals or a protected
left, and the number of lanes at a turn (GraphHopper can't use lane counts in
turn costs), so "main road" stands in for "several lanes". Nor can a turn's
cost depend on where it is (areas aren't allowed in turn costs), so
difficult places make their roads costly instead, and a U-turn's cost is
the same everywhere: turnarounds are checked on the finished route.

## The map

The image ships with the demo district's map, `services/routing/data/demo-houston.osm.pbf`
(the roads within about 12 km of the fictional district, © OpenStreetMap
contributors, ODbL; see `services/routing/data/README.md`). On first start
the engine builds its graph from the map, in seconds for that area.

For a real district:

1. Download your region's extract, e.g. your state from
   [Geofabrik](https://download.geofabrik.de) (`texas-latest.osm.pbf`).
   A state takes several GB of memory to build. To fetch just your
   district's area instead, edit the box in `services/routing/tools/overpass.ql`
   and follow `services/routing/tools/make_extract.py`.
2. Put it in the `maps` folder next to `docker-compose.prod.yml`.
3. In `.env`, set `ROUTING_MAP_FILE=/maps/texas-latest.osm.pbf` and, for a
   state, `ROUTING_JAVA_OPTS=-Xms1g -Xmx8g`.
4. `docker compose -f docker-compose.prod.yml up -d --build routing api`.
   Building the graph takes minutes for a state; the api waits for it.

Refresh the map every few months the same way, so new roads are known.

## Checking it

```bash
docker compose -f docker-compose.prod.yml exec api python scripts/check_routing_engine.py
```

prints a bus's route between two demo-district schools (or the two
`LAT,LON` points given), with its first few instructions, and exits 1 if
the engine doesn't answer. If the engine is down, scheduling falls back to
straight-line times (the api logs a warning) and drivers are told directions
aren't available right now.

## Settings

| Setting | Default | |
|---|---|---|
| `ISD_API_ROUTING_ENGINE_URL` | `http://routing:8989` in the Docker stacks | Blank turns the engine off (OpenRouteService or straight lines instead) |
| `ISD_API_ROUTING_ENGINE_PROFILE` | `school_bus` | |
| `ROUTING_MAP_FILE` | the demo map | Path inside the container, under `/maps` |
| `ROUTING_JAVA_OPTS` | `-Xms256m -Xmx1g` | Memory for the engine |

The engine isn't published to the host in production: only the api reaches
it. The development compose file (`docker-compose.yml`) publishes it on
`127.0.0.1:8989` for local work.

## Updating GraphHopper

`services/routing/Dockerfile` downloads the jar from Maven Central and checks
it against the SHA-256 Maven Central publishes; change both the version and
the checksum together.
