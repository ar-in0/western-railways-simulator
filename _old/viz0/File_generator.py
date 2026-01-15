import pandas as pd
import re
from pathlib import Path

excel_path = Path("wr-up.xlsx") #run this for wr-dn
sheets = pd.read_excel(excel_path, sheet_name=None, header=None, dtype=str, engine="openpyxl")

stops_set = set()
stop_times_list = []
trips_list = []

def clean_time(val):
    if pd.isna(val): return None
    val = str(val).strip()
    if not val or val.upper() in ["N/A", "-", "nan"]:
        return None
    m = re.match(r"^(\d{1,2})[:.](\d{2})$", val)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        return f"{hh:02d}:{mm:02d}:00"
    m2 = re.match(r"^(\d{1,2}):(\d{2})(:\d{2})?$", val)
    if m2:
        hh, mm = int(m2.group(1)), int(m2.group(2))
        return f"{hh:02d}:{mm:02d}:00"
    return None

def parse_trip_header(raw_header):
    if raw_header is None or str(raw_header).strip() == "":
        return None, None
    text = str(raw_header).replace("\n", " ")
    # pick the first 4–5 digit number as train_no
    m = re.search(r"\b(\d{4,5})\b", text)
    train_no = m.group(1) if m else None
    # crude headsign: last all-caps word
    headsigns = re.findall(r"[A-Z][A-Z]+", text)
    headsign = headsigns[-1] if headsigns else None
    return train_no, headsign

trip_occurrence = {}

# Iterate through all sheets
for sheet_name, df in sheets.items():
    rows, cols = df.shape
    r = 0
    while r < rows:
        row = df.iloc[r].astype(str).str.strip().tolist()
        if any("STATIONS" in str(cell).upper() for cell in row):
            header_row = r
            station_col = 0
            train_nums = df.iloc[header_row, 1:].dropna().tolist()

            for c, raw_header in enumerate(train_nums, start=1):
                train_no, headsign = parse_trip_header(raw_header)
                if not train_no:
                    continue

                trip_occurrence[train_no] = trip_occurrence.get(train_no, 0) + 1
                trip_id = f"{train_no}_{trip_occurrence[train_no]}"
                service_id = train_no  # placeholder

                trips_list.append({
                    "route_id": "WR-UP",
                    "service_id": service_id,
                    "trip_id": trip_id,
                    "trip_headsign": headsign if headsign else "",
                    "direction_id": 0
                })

                stop_sequence = 1
                rr = header_row + 1
                while rr < rows:
                    row2 = df.iloc[rr].astype(str).str.strip().tolist()
                    if any("STATIONS" in str(cell).upper() for cell in row2):
                        break

                    station = df.iat[rr, station_col]
                    if pd.isna(station) or str(station).strip() == "":
                        rr += 1
                        continue

                    station_name = str(station).strip().upper()
                    stops_set.add(station_name)

                    arr_val = df.iat[rr, c]
                    arr_time = clean_time(arr_val)
                    if arr_time is not None:
                        stop_times_list.append({
                            "trip_id": trip_id,
                            "arrival_time": arr_time,
                            "departure_time": arr_time,
                            "stop_id": station_name,
                            "stop_sequence": stop_sequence,
                            "pickup_type": 0,
                            "drop_off_type": 0,
                            "timepoint": 1
                        })
                        stop_sequence += 1

                    rr += 1
            r = rr
        else:
            r += 1

# Build stops.txt
stops_list = []
for stop_name in sorted(stops_set):
    stops_list.append({
        "stop_id": stop_name,
        "stop_name": stop_name,
        "stop_lat": "",
        "stop_lon": ""
    })

# Save
pd.DataFrame(stops_list).to_csv("stops3uptemp.txt", index=False)
pd.DataFrame(trips_list).to_csv("trips3uptemp.txt", index=False)
pd.DataFrame(stop_times_list).to_csv("stop_times3uptemp.txt", index=False)

print(f"GTFS files created for ALL sheets: {len(trips_list)} trips, {len(stop_times_list)} stop-times, {len(stops_list)} stops")





