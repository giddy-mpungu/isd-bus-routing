"""Turn an Overpass download (OSM XML) into the compact map file the routing
engine imports: PBF, without the editors' names, ids and edit history,
which routing doesn't need.

How the demo extract was made (docs/routing-engine.md):

    1. Download the roads around the demo district with the query in
       overpass.ql, e.g. with curl:
       curl --data-urlencode data@overpass.ql https://overpass-api.de/api/interpreter -o demo.osm
    2. python -P make_extract.py demo.osm ../data/demo-houston.osm.pbf

Needs pyosmium (pip install osmium); the engine itself doesn't.
"""

from __future__ import annotations

import sys
from pathlib import Path

import osmium


def main(source: str, target: str) -> None:
    out = Path(target)
    if out.exists():
        out.unlink()
    writer = osmium.SimpleWriter(str(out), filetype="pbf,add_metadata=false")
    counts = {"nodes": 0, "ways": 0, "relations": 0}
    try:
        for obj in osmium.FileProcessor(source):
            if obj.is_node():
                writer.add_node(obj)
                counts["nodes"] += 1
            elif obj.is_way():
                writer.add_way(obj)
                counts["ways"] += 1
            elif obj.is_relation():
                writer.add_relation(obj)
                counts["relations"] += 1
    finally:
        writer.close()
    size = out.stat().st_size / 1_000_000
    print(f"{out.name}: {counts}, {size:.1f} MB")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python -P make_extract.py SOURCE.osm TARGET.osm.pbf")
    main(sys.argv[1], sys.argv[2])
