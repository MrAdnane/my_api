"""Fill the DB with 1000+ rows.
Usage:
  python seed.py              -> generates 1500 sample rows
  python seed.py quakes.csv   -> imports a real CSV (USGS export works:
                                 columns place,mag,depth,latitude,longitude,time)
"""
import csv, random, sqlite3, sys
from datetime import datetime, timedelta
from app import DB, init_db

init_db()
rows = []
if len(sys.argv) > 1:
    for r in csv.DictReader(open(sys.argv[1], encoding="utf-8")):
        rows.append((r["place"], float(r["mag"]), float(r["depth"]),
                     float(r["latitude"]), float(r["longitude"]), r["time"]))
else:
    random.seed(1)
    places = ["Tokyo, Japan", "Santiago, Chile", "Lima, Peru", "Jakarta, Indonesia",
              "Athens, Greece", "Anchorage, Alaska", "Agadir, Morocco", "Wellington, New Zealand",
              "Istanbul, Turkey", "Mexico City, Mexico"]
    start = datetime(2020, 1, 1)
    for _ in range(1500):
        rows.append((random.choice(places), round(random.uniform(2, 8.5), 1),
                     round(random.uniform(1, 300), 1), round(random.uniform(-60, 70), 4),
                     round(random.uniform(-180, 180), 4),
                     (start + timedelta(minutes=random.randint(0, 2_000_000))).isoformat()))
with sqlite3.connect(DB) as c:
    c.executemany("INSERT INTO earthquakes(place,magnitude,depth_km,latitude,longitude,occurred_at) VALUES(?,?,?,?,?,?)", rows)
print(f"Inserted {len(rows)} rows")
