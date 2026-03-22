"""
Mumbai Predictive Logistics Engine — Simulation Data Generator
Generates 3 event streams: GPS Telemetry, Sensor Telemetry, Package Manifests
100 vans, 7 days, Mumbai geography
"""

import uuid, random, math, json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import os

# ─── Reproducibility ────────────────────────────────────────────
random.seed(42)
np.random.seed(42)

# ─── Mumbai Geography ───────────────────────────────────────────
# Real Mumbai delivery zones with lat/lon anchors
ZONES = {
    "BKC":          {"lat": 19.0596, "lon": 72.8656, "label": "Bandra Kurla Complex"},
    "Dharavi":      {"lat": 19.0418, "lon": 72.8544, "label": "Dharavi"},
    "Andheri":      {"lat": 19.1197, "lon": 72.8464, "label": "Andheri West"},
    "Lower_Parel":  {"lat": 18.9938, "lon": 72.8258, "label": "Lower Parel"},
    "Worli":        {"lat": 19.0178, "lon": 72.8178, "label": "Worli"},
    "Dadar":        {"lat": 19.0180, "lon": 72.8417, "label": "Dadar"},
    "Powai":        {"lat": 19.1176, "lon": 72.9060, "label": "Powai"},
    "Bandra":       {"lat": 19.0544, "lon": 72.8402, "label": "Bandra West"},
    "Kurla":        {"lat": 19.0728, "lon": 72.8826, "label": "Kurla"},
    "Ghatkopar":    {"lat": 19.0862, "lon": 72.9077, "label": "Ghatkopar"},
    "Chembur":      {"lat": 19.0620, "lon": 72.9001, "label": "Chembur"},
    "Malad":        {"lat": 19.1865, "lon": 72.8486, "label": "Malad West"},
}

# Medical facility destinations (LIFE_CRITICAL delivery points)
MEDICAL_DESTINATIONS = [
    {"name": "Hinduja Hospital, Mahim",     "lat": 19.0414, "lon": 72.8370},
    {"name": "Kokilaben Hospital, Andheri", "lat": 19.1362, "lon": 72.8264},
    {"name": "Lilavati Hospital, Bandra",   "lat": 19.0524, "lon": 72.8259},
    {"name": "KEM Hospital, Parel",         "lat": 18.9960, "lon": 72.8409},
    {"name": "Nanavati Hospital, Vile Parle","lat": 19.0990, "lon": 72.8388},
]

# Depots (van starting points)
DEPOTS = [
    {"name": "Andheri Depot",  "lat": 19.1197, "lon": 72.8464, "zone": "Andheri"},
    {"name": "Dadar Depot",    "lat": 19.0180, "lon": 72.8417, "zone": "Dadar"},
    {"name": "Kurla Depot",    "lat": 19.0728, "lon": 72.8826, "zone": "Kurla"},
]

N_VANS = 100
N_DAYS = 7
INTERVAL_SEC = 300          # 5-minute intervals (Colab-friendly — scales to 5-sec in prod)
START_DATE = datetime(2024, 3, 11)  # Monday

# ─── H3-like geo hash (simplified without h3 library) ───────────
def simple_geohash(lat, lon, precision=6):
    """Simplified spatial hash at ~170m resolution (approximates H3 L9)"""
    lat_q = round(lat * precision, 0) / precision
    lon_q = round(lon * precision, 0) / precision
    return f"{lat_q:.4f}_{lon_q:.4f}"

# ─── Van configuration ──────────────────────────────────────────
def create_van_fleet(n=N_VANS):
    vans = []
    for i in range(n):
        depot = DEPOTS[i % len(DEPOTS)]
        van_id = f"VAN-{str(i+1).zfill(4)}"
        # 10% have faulty GPS (jitter vans)
        is_jitter = (i % 10 == 7)
        vans.append({
            "van_id": van_id,
            "depot": depot,
            "current_lat": depot["lat"] + np.random.normal(0, 0.005),
            "current_lon": depot["lon"] + np.random.normal(0, 0.005),
            "heading": random.uniform(0, 360),
            "is_jitter_van": is_jitter,
            "fuel_pct": random.uniform(60, 100),
            "tyre_psi": [random.uniform(33, 36) for _ in range(4)],
            "engine_temp": random.uniform(85, 95),
            "odometer": random.randint(10000, 80000),
            "firmware": random.choice(["v2.3.1", "v2.4.1", "v2.4.2"]),
            # Van 402 is the special case from the interview scenario
            "is_van402": (van_id == "VAN-0042"),
        })
    return vans

# ─── Traffic speed model ────────────────────────────────────────
def get_speed_kmh(dt, zone_from, zone_to, is_friday_afternoon):
    hour = dt.hour
    # Base speed depends on time of day
    if 7 <= hour <= 10 or 17 <= hour <= 21:
        base = random.gauss(15, 4)   # Mumbai rush hour
    elif 22 <= hour or hour <= 5:
        base = random.gauss(45, 5)   # Night
    else:
        base = random.gauss(28, 6)   # Daytime

    # Friday afternoon regime change — THE KEY INSIGHT
    if is_friday_afternoon and hour >= 14 and hour <= 19:
        # 400% variance increase — std dev multiplied ~4x
        std_dev_multiplier = 4.0
        base = random.gauss(base * 0.7, 4 * std_dev_multiplier)

    return max(3.0, min(70.0, base))

# ─── GPS position update ────────────────────────────────────────
def update_position(van, speed_kmh, dt_sec, is_friday_afternoon, hour):
    dist_km = (speed_kmh * dt_sec) / 3600.0
    # Wander towards a random zone
    target_zone = random.choice(list(ZONES.values()))
    dlat = target_zone["lat"] - van["current_lat"]
    dlon = target_zone["lon"] - van["current_lon"]
    dist_to_target = math.sqrt(dlat**2 + dlon**2)

    if dist_to_target > 0.001:
        move_lat = (dlat / dist_to_target) * (dist_km / 111.0)
        move_lon = (dlon / dist_to_target) * (dist_km / (111.0 * math.cos(math.radians(van["current_lat"]))))
    else:
        move_lat = np.random.normal(0, 0.0001)
        move_lon = np.random.normal(0, 0.0001)

    van["current_lat"] += move_lat + np.random.normal(0, 0.0001)
    van["current_lon"] += move_lon + np.random.normal(0, 0.0001)

    # Heading
    if dist_to_target > 0.001:
        van["heading"] = (math.degrees(math.atan2(move_lon, move_lat)) + 360) % 360

    # GPS jitter vans: add ±50m noise (≈0.00045 degrees)
    raw_lat, raw_lon = van["current_lat"], van["current_lon"]
    accuracy = 5.0
    if van["is_jitter_van"]:
        noise = 0.00045
        raw_lat += np.random.normal(0, noise)
        raw_lon += np.random.normal(0, noise)
        accuracy = random.uniform(45, 80)
        # Random heading for jitter vans
        van["heading"] = random.uniform(0, 360)

    return raw_lat, raw_lon, accuracy

# ─── Sensor update ──────────────────────────────────────────────
def update_sensors(van, day_num, hour, is_van402_incident):
    # Gradual tyre wear
    van["tyre_psi"] = [p - random.uniform(0, 0.005) for p in van["tyre_psi"]]
    # Temperature fluctuation
    van["engine_temp"] += np.random.normal(0, 0.5)
    van["engine_temp"] = np.clip(van["engine_temp"], 80, 105)
    # Fuel consumption
    van["fuel_pct"] -= random.uniform(0.01, 0.05)
    van["fuel_pct"] = max(5.0, van["fuel_pct"])
    van["odometer"] += random.randint(0, 1)

    # Van #402 incident: Day 3, 14:30 — PSI drop
    if is_van402_incident:
        van["tyre_psi"][0] -= 5.0  # Front-left drops 5 PSI

    psi_min = min(van["tyre_psi"])
    # Alert flags bitmask
    flags = 0
    if van["engine_temp"] > 100: flags |= 1   # Bit 0: engine warning
    if psi_min < 28:             flags |= 2   # Bit 1: tyre warning
    if van["fuel_pct"] < 15:     flags |= 4   # Bit 2: fuel low

    # Health score
    tyre_score   = min(100, max(0, (psi_min - 20) / 16 * 100))
    engine_score = min(100, max(0, (110 - van["engine_temp"]) / 30 * 100))
    fuel_score   = min(100, van["fuel_pct"])
    health_score = 0.4 * tyre_score + 0.4 * engine_score + 0.2 * fuel_score

    safe_to_continue = (psi_min >= 26 and van["engine_temp"] < 105 and health_score > 30)

    return psi_min, flags, health_score, safe_to_continue

# ─── Package manifest generation ────────────────────────────────
def generate_packages_for_van(van_id, day_dt, n_packages=8):
    packages = []
    # Priority distribution: 5% LIFE_CRITICAL, 20% PREMIUM, 75% STANDARD
    for i in range(n_packages):
        r = random.random()
        if r < 0.05:
            priority = "LIFE_CRITICAL"
            dest = random.choice(MEDICAL_DESTINATIONS)
            sla_hours = random.uniform(0.5, 2.0)
        elif r < 0.25:
            priority = "PREMIUM"
            dest_zone = random.choice(list(ZONES.values()))
            dest = {"name": dest_zone["label"], "lat": dest_zone["lat"] + np.random.normal(0, 0.003),
                    "lon": dest_zone["lon"] + np.random.normal(0, 0.003)}
            sla_hours = random.uniform(2, 4)
        else:
            priority = "STANDARD"
            dest_zone = random.choice(list(ZONES.values()))
            dest = {"name": dest_zone["label"], "lat": dest_zone["lat"] + np.random.normal(0, 0.005),
                    "lon": dest_zone["lon"] + np.random.normal(0, 0.005)}
            sla_hours = random.uniform(4, 8)

        load_time = day_dt + timedelta(hours=random.uniform(7, 10))
        sla_time  = load_time + timedelta(hours=sla_hours)

        packages.append({
            "event_id":           str(uuid.uuid4()),
            "van_id":             van_id,
            "timestamp_utc":      int(load_time.timestamp() * 1000),
            "ingested_utc":       int((load_time + timedelta(seconds=1)).timestamp() * 1000),
            "event_type":         "LOADED",
            "package_id":         str(uuid.uuid4()),
            "priority_class":     priority,
            "delivery_sla_utc":   int(sla_time.timestamp() * 1000),
            "dest_lat":           round(dest["lat"], 6),
            "dest_lon":           round(dest["lon"], 6),
            "dest_name":          dest["name"],
            "time_to_sla_sec":    int(sla_hours * 3600),
            "weight_kg":          round(random.uniform(0.5, 25.0), 2),
            "requires_cold_chain": priority == "LIFE_CRITICAL" and random.random() < 0.4,
            "special_handling":   ["FRAGILE"] if random.random() < 0.1 else [],
            "schema_version":     1,
        })
    return packages

# ─── MAIN GENERATION ────────────────────────────────────────────
def generate_all(output_dir="data/sample"):
    os.makedirs(output_dir, exist_ok=True)
    print("Initialising Mumbai fleet simulation...")
    print(f"  {N_VANS} vans  |  {N_DAYS} days  |  {INTERVAL_SEC}s intervals")
    print(f"  10% jitter vans (Van-0007, 0017, 0027 ... etc)")
    print(f"  Van #0042 = Van 402 incident on Day 3 at 14:30\n")

    vans = create_van_fleet(N_VANS)
    gps_rows, sensor_rows, manifest_rows = [], [], []

    for day in range(N_DAYS):
        day_dt = START_DATE + timedelta(days=day)
        day_name = day_dt.strftime("%A")
        is_friday = day_dt.weekday() == 4

        print(f"  Generating Day {day+1}/7: {day_name} {day_dt.strftime('%d %b')} {'[FRIDAY — variance spike active]' if is_friday else ''}")

        # Generate manifest events at start of each day
        for van in vans:
            pkgs = generate_packages_for_van(van["van_id"], day_dt)
            manifest_rows.extend(pkgs)

        # Simulate operating hours: 7am to 9pm
        t = day_dt.replace(hour=7, minute=0, second=0)
        end_t = day_dt.replace(hour=21, minute=0, second=0)

        while t < end_t:
            hour = t.hour
            is_friday_afternoon = is_friday and 14 <= hour <= 19

            for van in vans:
                # Van 402 incident check
                is_van402_incident = (
                    van["is_van402"] and
                    day == 2 and  # Day 3 (0-indexed)
                    hour == 14 and
                    t.minute == 30
                )

                speed = get_speed_kmh(t, None, None, is_friday_afternoon)
                raw_lat, raw_lon, accuracy = update_position(van, speed, INTERVAL_SEC, is_friday_afternoon, hour)
                psi_min, flags, health, safe = update_sensors(van, day, hour, is_van402_incident)

                ts_ms       = int(t.timestamp() * 1000)
                ingested_ms = ts_ms + random.randint(200, 800)

                # GPS event
                gps_rows.append({
                    "event_id":         str(uuid.uuid4()),
                    "van_id":           van["van_id"],
                    "timestamp_utc":    ts_ms,
                    "ingested_utc":     ingested_ms,
                    "lat":              round(raw_lat, 6),
                    "lon":              round(raw_lon, 6),
                    "geo_hash":         simple_geohash(raw_lat, raw_lon),
                    "speed_kmh":        round(speed, 2),
                    "heading_deg":      round(van["heading"], 1),
                    "gps_accuracy_m":   round(accuracy, 1),
                    "altitude_m":       round(random.uniform(5, 15), 1),
                    "satellites_locked": random.randint(6, 12) if not van["is_jitter_van"] else random.randint(3, 6),
                    "fix_type":         "GPS_3D" if not van["is_jitter_van"] else random.choice(["GPS_2D", "GPS_3D"]),
                    "is_jitter_van":    van["is_jitter_van"],  # label for analysis
                    "day_name":         day_name,
                    "is_friday_afternoon": is_friday_afternoon,
                    "schema_version":   1,
                })

                # Sensor event
                sensor_rows.append({
                    "event_id":         str(uuid.uuid4()),
                    "van_id":           van["van_id"],
                    "timestamp_utc":    ts_ms,
                    "ingested_utc":     ingested_ms,
                    "tyre_psi_fl":      round(van["tyre_psi"][0], 2),
                    "tyre_psi_fr":      round(van["tyre_psi"][1], 2),
                    "tyre_psi_rl":      round(van["tyre_psi"][2], 2),
                    "tyre_psi_rr":      round(van["tyre_psi"][3], 2),
                    "tyre_psi_min":     round(psi_min, 2),
                    "engine_temp_c":    round(van["engine_temp"], 1),
                    "engine_rpm":       random.randint(800, 3500),
                    "fuel_level_pct":   round(van["fuel_pct"], 1),
                    "speed_kmh":        round(speed, 2),
                    "odometer_km":      van["odometer"],
                    "alert_flags":      flags,
                    "health_score":     round(health, 1),
                    "safe_to_continue": safe,
                    "firmware_version": van["firmware"],
                    "is_van402":        van["is_van402"],  # label for analysis
                    "day_name":         day_name,
                    "schema_version":   1,
                })

            t += timedelta(seconds=INTERVAL_SEC)

    # Save to CSV
    gps_df      = pd.DataFrame(gps_rows)
    sensor_df   = pd.DataFrame(sensor_rows)
    manifest_df = pd.DataFrame(manifest_rows)

    gps_path      = os.path.join(output_dir, "gps_telemetry.csv")
    sensor_path   = os.path.join(output_dir, "sensor_telemetry.csv")
    manifest_path = os.path.join(output_dir, "package_manifest.csv")

    gps_df.to_csv(gps_path,      index=False)
    sensor_df.to_csv(sensor_path, index=False)
    manifest_df.to_csv(manifest_path, index=False)

    print(f"\nGeneration complete:")
    print(f"  GPS telemetry:      {len(gps_df):,} rows  → {gps_path}")
    print(f"  Sensor telemetry:   {len(sensor_df):,} rows  → {sensor_path}")
    print(f"  Package manifests:  {len(manifest_df):,} rows  → {manifest_path}")

    return gps_df, sensor_df, manifest_df

if __name__ == "__main__":
    generate_all()
