# Your district's map

Put your region's OpenStreetMap extract here (for example a state file from
https://download.geofabrik.de), then set `ROUTING_MAP_FILE=/maps/<file>.osm.pbf`
in `.env` and restart the `routing` service. Without one, the routing engine
uses the demo district's map. See docs/routing-engine.md.
