import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from pathlib import Path
import re

# ---------- pick available files ----------
def pick(base):
    for name in [f"{base}_all.txt"]:
        if Path(name).exists(): return name
    raise FileNotFoundError(f"Could not find any of: {base}_all.txt, {base}_table1.txt, {base}.txt")

stops_fp = pick("stops")
trips_fp = pick("trips")
stop_times_fp = pick("stop_times")

stops = pd.read_csv(stops_fp, dtype=str)
trips = pd.read_csv(trips_fp, dtype=str)
stop_times = pd.read_csv(stop_times_fp, dtype=str)

# ---------- normalize ----------
def norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip().upper())

stops["stop_name_norm"] = stops["stop_name"].apply(norm)
stop_times["trip_id"] = stop_times["trip_id"].astype(str).str.strip()
stop_times["stop_id"] = stop_times["stop_id"].astype(str).str.strip()

# map stop_id -> stop_name (original, for labels) and -> normalized
id_to_name = dict(zip(stops["stop_id"], stops["stop_name"]))
id_to_name_norm = dict(zip(stops["stop_id"], stops["stop_name_norm"]))

# parse times safely (expect HH:MM:SS)
def to_dt(t):
    try:
        return datetime.strptime(str(t).strip(), "%H:%M:%S")
    except Exception:
        return None

stop_times["time_dt"] = stop_times["arrival_time"].apply(to_dt)

# ---------- fixed corridor order for axis (Churchgate -> Virar) ----------
order_norm = [
    "CHURCHGATE","MARINE LINES","CHARNI ROAD","GRANT ROAD","M'BAI CENTRAL (L)","MAHALAKSHMI",
    "LOWER PAREL","PRABHADEVI","DADAR","MATUNGA ROAD","MAHIM JN.","BANDRA","KHAR ROAD",
    "SANTA CRUZ","VILE PARLE","ANDHERI","JOGESHWARI","RAM MANDIR","GOREGAON","MALAD",
    "KANDIVLI","BORIVALI","DAHISAR","MIRA ROAD","BHAYANDAR","NAIGAON","VASAI ROAD",
    "NALLA SOPARA","VIRAR"
]

# build display labels from your stops file (so casing matches your data)
norm_to_display = {norm(v): v for v in stops["stop_name"].tolist()}
ordered_labels = [norm_to_display[n] for n in order_norm if n in norm_to_display]
pos = {norm(lbl): i for i, lbl in enumerate(ordered_labels)}  # single mapping for BOTH directions

# ---------- trip groups (one group = one color) ----------
trip_groups = [[
    90001, 90036, 90079, 90148, 90193, 90258, 90309, 90384,
    90441, 90494, 90543, 90602, 90671, 90746, 90813, 90886,
    90955], [92001, 92012, 92029, 92046, 92069, 92088, 92093, 92112, 92117, 92132, 92133, 92152, 92159, 92182, 92183, 92192, 92203
]]
trip_groups = [[str(t) for t in g] for g in trip_groups]

# ---------- plotting ----------
plt.figure(figsize=(16, 11))
ax = plt.gca()

colors = plt.cm.tab10.colors
found_any = False

for gi, group in enumerate(trip_groups):
    color = colors[gi % len(colors)]  # same color for all trips in this group
    group_label_added = False

    for tid in group:
        # match exact trip_id OR trip_id with a suffix like "90001_2"
        mask = stop_times["trip_id"].str.match(rf"^{re.escape(tid)}(_\d+)?$")
        df = stop_times[mask].copy()
        if df.empty:
            continue

        df = df.dropna(subset=["time_dt"])
        if df.empty:
            continue

        # attach names and y-positions (same mapping for both directions)
        df["stop_name"] = df["stop_id"].map(id_to_name)
        df["stop_name_norm"] = df["stop_id"].map(id_to_name_norm)
        df["y"] = df["stop_name_norm"].map(pos)

        # keep only stations in our corridor order
        df = df.dropna(subset=["y"])
        if df.empty:
            continue

        # sort properly to draw lines in stop order
        if "stop_sequence" in df.columns:
            df["stop_sequence_num"] = pd.to_numeric(df["stop_sequence"], errors="coerce")
            df = df.sort_values(["trip_id", "stop_sequence_num", "time_dt"])
        else:
            df = df.sort_values(["time_dt", "y"])

        ax.plot(
            df["time_dt"], df["y"],
            marker="o", linestyle="-", color=color,
            label=f"Group {gi+1}" if not group_label_added else None,
            alpha=0.8
        )
        group_label_added = True
        found_any = True

if not found_any:
    print("No matching trips found on this corridor order.")

# y-axis: set ticks to our ordered labels and put CHURCHGATE at the TOP
ax.set_yticks(range(len(ordered_labels)))
ax.set_yticklabels(ordered_labels)
ax.invert_yaxis()  # Churchgate → Virar from top to bottom

# x-axis formatting
ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
plt.xlabel("Time of Day")
plt.ylabel("Stations (Churchgate ↔ Virar)")
plt.title("Station vs Time (Western Line — Up & Down, same color)")
plt.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0), fontsize="small")
plt.grid(True, linestyle="--", alpha=0.4)
plt.tight_layout()

plt.savefig("plot3updown.png", dpi=300)
plt.close()

print("plot3updown.png")

