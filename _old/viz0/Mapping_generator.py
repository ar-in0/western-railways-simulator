from pathlib import Path
import csv
from collections import defaultdict

STOP_TIMES = Path("stop_times_all.txt")
TRIPS = Path("trips_all.txt")
OUT = Path("mapping.txt")

# helper: convert HH:MM:SS → seconds
def time_to_seconds(t):
    try:
        h, m, s = map(int, t.split(":"))
        return h * 3600 + m * 60 + s
    except Exception:
        return None

# 1) Parse stop_times → get start & end info per trip
trip_start, trip_end = {}, {}
with STOP_TIMES.open(newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    rows_by_trip = {}
    for r in reader:
        tid = r['trip_id'].strip()
        rows_by_trip.setdefault(tid, []).append(r)

    for tid, rows in rows_by_trip.items():
        try:
            rows_sorted = sorted(rows, key=lambda x: int(x.get('stop_sequence', '0') or '0'))
        except Exception:
            rows_sorted = rows
        first, last = rows_sorted[0], rows_sorted[-1]
        start_time = first.get('departure_time') or first.get('arrival_time')
        end_time = last.get('arrival_time') or last.get('departure_time')
        start_sec, end_sec = time_to_seconds(start_time), time_to_seconds(end_time)
        if start_sec is None or end_sec is None:
            continue
        trip_start[tid] = (start_sec, first['stop_id'])
        trip_end[tid] = (end_sec, last['stop_id'])

# 2) Collect trip_ids from trips_all.txt
trip_ids = []
with TRIPS.open(newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    if 'trip_id' in reader.fieldnames:
        trip_ids = [r['trip_id'].strip() for r in reader if r['trip_id'].strip()]
    else:
        trip_ids = list(trip_start.keys())

candidate_trip_ids = [tid for tid in trip_ids if tid in trip_start and tid in trip_end]

# trip object
class Trip:
    def __init__(self, tid, start_sec, start_stop, end_sec, end_stop):
        self.tid, self.start_sec, self.start_stop, self.end_sec, self.end_stop = (
            tid, start_sec, start_stop, end_sec, end_stop
        )

trips = [Trip(tid, *trip_start[tid], *trip_end[tid]) for tid in candidate_trip_ids]
trips.sort(key=lambda x: (x.start_sec, x.tid))

# index trips by start station
starts_by_station = defaultdict(list)
for t in trips:
    starts_by_station[t.start_stop].append(t)
for st in starts_by_station:
    starts_by_station[st].sort(key=lambda x: (x.start_sec, x.tid))

assigned, chains = set(), []
MAX_GAP = 15 * 60  # 15 min

# greedy chaining
for t in trips:
    if t.tid in assigned:
        continue
    chain = [t.tid]
    assigned.add(t.tid)
    last_end_station, last_end_time = t.end_stop, t.end_sec
    while True:
        candidates = starts_by_station.get(last_end_station, [])
        next_trip = None
        for c in candidates:
            if c.tid in assigned:
                continue
            if 0 <= c.start_sec - last_end_time <= MAX_GAP:
                next_trip = c
                break
        if not next_trip:
            break
        chain.append(next_trip.tid)
        assigned.add(next_trip.tid)
        last_end_station, last_end_time = next_trip.end_stop, next_trip.end_sec
    chains.append(chain)

# write mapping.txt
with OUT.open("w", encoding="utf-8") as f:
    for i, chain in enumerate(chains, 1):
        f.write(f"Train{i}: {', '.join(chain)}\n")
