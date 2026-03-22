# System Flows & Message Architecture

Complete end-to-end flows showing how events move through the system, when decisions are made, and how drivers are notified.

---

## 1. Event Flow: Three Integration Points

```
┌─────────────────────────────────────────────────────────────────────┐
│                    VAN ECU / GPS Unit (Physical)                    │
└────────────────────────────┬────────────────────────────────────────┘
                             │ (MQTT/AMQP, TLS, 5-sec heartbeat)
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│          Azure IoT Hub (Device Authentication, Routing)             │
└────────────────────────────┬────────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│        API Management (Rate Limit: 5 msg/van/sec, TLS)             │
└────────────────────────────┬────────────────────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         ▼                   ▼                   ▼
    GPS Telemetry      Sensor Telemetry    Package Manifest
   (5-sec cadence)   (5-sec + threshold)   (event-driven)
         │                   │                   │
         ├─ lat, lon         ├─ tyre_psi_min    ├─ priority_class
         ├─ speed_kmh        ├─ engine_temp     ├─ delivery_sla
         ├─ heading          ├─ fuel_level      ├─ package_id
         ├─ accuracy_m       ├─ health_score    ├─ weight_kg
         └─ geo_hash         ├─ safe_to_continue└─ special_handling
                             └─ anomaly_flags
         │                   │                   │
         └───────────────────┼───────────────────┘
                             │
                   (Avro Schema Validation)
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         ▼                   ▼                   ▼
    [32 partitions]  [16 partitions]      [8 partitions]
    (H3 geo_hash)    (van_id)              (van_id)
         │                   │                   │
         └───────────────────┴───────────────────┘
                             │
          Azure Event Hubs (Kafka API, 7-day retention)
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
    [HOT PATH]         [WARM PATH]          [COLD PATH]
      <2 sec              <30 sec             Batch
         │                   │                   │
```

---

## 2. Hot Path: Real-Time Anomaly Detection (<2s)

### Flow: GPS Telemetry Processing

```
GPS Telemetry Event
├─ van_id: "VAN-0042"
├─ lat: 19.0760
├─ lon: 72.8777
├─ speed_kmh: 18.5
├─ accuracy_m: 4.2
├─ heading_deg: 245
└─ geo_hash: "ttfxq"
       │
       ▼
[Stream Analytics Job 1: Kalman Filter + GPS Jitter Detection]
       │
       ├─ Kalman smooth [lat, lon] on 2D state
       │  ├─ Process noise Q = 1e-7
       │  └─ Observation noise R = (accuracy_m / 111000)²
       │
       ├─ Extract covariance = trace(P)
       │
       └─ 3-Signal Ensemble
          ├─ Signal 1: Kalman covariance > 75th percentile? → JITTER_CANDIDATE
          ├─ Signal 2: Heading coherence < 0.4? → JITTER_CANDIDATE
          ├─ Signal 3: Reported accuracy > 40m? → JITTER_CANDIDATE
          │
          └─ Decision: JITTER if ≥2 signals agree (confidence = n_signals/3)
       │
       ▼
[Output: Redis Cache (10-sec TTL)]
├─ Key: jitter:van-id:timestamp
├─ Value: {jitter_status, covariance, confidence}
└─ Also: h3:ttfxq:vans = set(van_id1, van_id2, ...)  [for peer lookup]
       │
       ▼
[Alert: If JITTER detected]
├─ Log to Cosmos DB (append-only)
├─ Increment alert counter
└─ If confidence > 0.9 → Flag for driver (batched notification, 2/hr throttle)
```

### Flow: Sensor Telemetry Processing

```
Sensor Telemetry Event
├─ van_id: "VAN-0042"
├─ tyre_psi_min: 28.1  (pre-computed from 4 tyre readings)
├─ engine_temp_c: 91.2
├─ fuel_level_pct: 42.0
├─ health_score: 0.87
├─ safe_to_continue: true  (pre-computed gate at source)
└─ anomaly_flags: 0x05  (bitmask: bit0=low_fuel, bit1=overtemp)
       │
       ▼
[Stream Analytics Job 2: Isolation Forest Anomaly Detection]
       │
       ├─ Load pre-fitted model for firmware version "3.2.1"
       │  (trained weekly per firmware to handle ECU baseline variance)
       │
       ├─ Features → [28.1, 91.2, 42.0, 18.5, 0.87]  [tyre, temp, fuel, speed, health]
       │
       ├─ Anomaly score = iso.score_samples(X)  (lower = more anomalous)
       │  └─ Compare to 75th percentile baseline for this firmware version
       │
       └─ Prediction: ANOMALOUS if score < threshold, confidence = contamination_rate
       │
       ▼
[Output: Two Destinations]
       │
       ├─ [1] Cache → Redis
       │  ├─ Key: sensor:van-id
       │  ├─ Value: {tyre_psi, temp, fuel, safe_to_continue, anomaly_detected, score}
       │  └─ TTL: 10 sec (high update frequency)
       │
       └─ [2] Audit → Cosmos DB
           ├─ Record: {van_id, timestamp, anomaly_score, is_anomalous, decision}
           └─ TTL: 30 days (compliance)
       │
       ▼
[Alert: If Anomaly + safe_to_continue=false]
├─ CRITICAL: Vehicle unsafe, must HOLD
├─ Log alert to ops dashboard (real-time)
├─ Dispatcher notified immediately
└─ Driver gets notification: "Vehicle diagnostic failure, please pullover"
```

---

## 3. Warm Path: Route Optimization & AI Decisions (<30s)

### Flow: Package Manifest → Route Decision

```
Package Manifest Event (LIFE_CRITICAL package arrives)
├─ manifest_id: "MANIFEST-2026-03-22-001"
├─ van_id: "VAN-0042"
├─ package_id: "PKG-1001"
├─ priority_class: "LIFE_CRITICAL"  ← TRIGGERS LANGGRAPH AGENT
├─ cargo: "3× blood units O-, 4h expiry"
├─ delivery_sla_utc: "2026-03-22T15:30:00Z"  (30 min from now)
├─ dest_lat: 19.0156, dest_lon: 72.8295  (Hospital Central)
└─ special_handling: ["FRAGILE", "COLD_CHAIN"]
       │
       ▼
       ┌─────────────────────────────────────────┐
       │   [DECISION GATE: priority_class]       │
       ├─────────────────────────────────────────┤
       │ Is LIFE_CRITICAL?                       │
       │  ├─ Yes → Route to LangGraph AI Agent   │
       │  └─ No → Route to OR-Tools (deterministic)
       └─────────────────────────────────────────┘
       │
       ▼ (YES → LANGGRAPH AI AGENT)
       │
[T=0-2s: Pre-flight Checks]
       │
       ├─ Fetch van state from Cosmos DB
       │  └─ Van #42: fuel=42%, health_score=0.94, last_service=2026-03-10
       │
       ├─ Fetch latest sensor cache from Redis
       │  └─ safe_to_continue = true ✓
       │
       └─ Fetch jitter status from Redis
           └─ jitter_status = NORMAL ✓
       │
       │ [If any gate fails → Return HELD with reason]
       │
       ▼
[T=2-5s: LangGraph Agent Invocation]
       │
       ├─ Tool 1: route_search(van_id="VAN-0042", dest_lat=19.0156, dest_lon=72.8295)
       │  └─ Returns: [Route A (12km), Route B (15km), Route C (14km)]
       │
       ├─ Tool 2: eta_predict(route=A, dow=1, hour=14)
       │  ├─ Features: [hour=14, dow=1, is_friday=0, fri_pm_flag=0, speed_kmh=18.5, ...]
       │  ├─ Friday regime check: dow=1 → NOT Friday, use standard model
       │  └─ Returns: {eta_min=28, p90_eta_min=30, confidence=0.96}
       │
       ├─ Tool 3: anomaly_lookup(van_id="VAN-0042")
       │  └─ Returns: {incidents_7d=0, alerts_24h=0, risk_score=0.05}
       │
       └─ Tool 4: traffic_regime_detect(zone_h3="ttfxq", hour=14)
           ├─ Rolling std-dev in zone last 60 min = 12.5 km/h
           ├─ Baseline Monday 14:00 std-dev = 8.2 km/h
           └─ Regime spike = 1.52× (normal, not Friday regime)
       │
       ▼
[T=5-15s: Agent Reasoning (Chain-of-Thought)]
       │
       Gate 1: safe_to_continue = true ✓
       Gate 2: time_to_sla = 1800 sec (30 min) ✓
       Gate 3: ETA 28 min < SLA 30 min ✓  (buffer: 2 min)
       Gate 4: Risk factors: none ✓
       Gate 5: Driver rating: 4.9/5, history clean ✓
       │
       └─ Decision: APPROVED
          ├─ Chosen route: Route A (south_ring)
          ├─ ETA: 28 minutes
          ├─ Confidence: 0.96
          └─ Reasoning: "ETA 28m << SLA 30m; sensor healthy; low-risk driver"
       │
       ▼
[T=15-20s: Decision Output]
       │
       Decision JSON → Cosmos DB (audit log)
       ├─ decision_id: "DECISION-2026-03-22-042-001"
       ├─ status: "APPROVED"
       ├─ routes_evaluated: 3
       ├─ chosen_waypoints: [...]
       ├─ eta_minutes: 28
       ├─ confidence_score: 0.96
       ├─ timestamp_completed_utc: "2026-03-22T14:12:45.123Z"
       └─ reasoning_chain: [...]
       │
       ▼
[T=20-30s: Driver Notification]
       │
       Route message → Notification Queue
       ├─ Check throttle: notif:throttle:VAN-0042 (current: 0/2 per hour)
       ├─ Compose message: "3 blood units ready. Hospital Central route (28 min ETA). Stay on south_ring."
       │
       └─ Send via Notification Hubs
           ├─ Protocol: APNS (iOS) + FCM (Android)
           ├─ Delivery: <2 sec to driver app
           └─ Throttle: increment counter (TTL 3600 sec)
```

### Flow: Rerouting Scenario (When & Why)

```
Scenario: Van #103 hits unexpected traffic jam on primary route
         ETA drifts from 25 min → 38 min (SLA = 45 min)
         
         │
         ▼
[Continuous Monitor: ETA Drift Detection]
         │
         ├─ Current position: H3 zone "abc123"
         ├─ Current speed: 12 km/h (down from 22 km/h baseline)
         ├─ Remaining distance: 18 km
         ├─ New ETA: estimated 38 min
         ├─ SLA: 45 min
         └─ Buffer: 7 min (acceptable but risky)
         │
         ▼
[Decision: Recompute Route?]
         │
         ├─ If ETA drift > 10% & buffer < 10 min → REROUTE
         │  (Current: 38 min ETA, 45 min SLA → 7 min buffer = 15% → REROUTE)
         │
         └─ Call LangGraph Agent again with current position
             │
             ├─ Tool: route_search(current_lat=19.050, current_lon=72.890)
             │  └─ Returns: [Route A (primary, 38 min), Route B (inland, 36 min), Route C (eastbound, 31 min)]
             │
             └─ Agent evaluates new ETA vs alternatives
                 ├─ Route C (eastbound): 31 min ETA → buffer 14 min ✓ (preferred)
                 ├─ But: Toll gate + 2 km detour (new coordinates)
                 └─ Final decision: REROUTED to eastbound, save 7 min
         │
         ▼
[Reroute Notification to Driver]
         │
         Message: "Traffic jam detected. Rerouting you via Eastbound (31 min instead of 38). New GPS coords sent."
         │
         └─ Old throttle count NOT reset (still counts toward 2/hr quota)
             [Rationale: avoid notification spam]
```

---

## 4. Schema Deep Dive: Main Columns & Variations

### 4.1 GPS Telemetry Schema

```json
{
  "type": "record",
  "name": "GPSTelemetry",
  "namespace": "com.logistics.events",
  "fields": [
    {
      "name": "event_id",
      "type": "string",
      "doc": "UUID v4, unique per device, partition-agnostic ID"
    },
    {
      "name": "van_id",
      "type": "string",
      "doc": "Vehicle identifier (VAN-0001 format)"
    },
    {
      "name": "timestamp_utc",
      "type": "long",
      "doc": "Epoch milliseconds (source time on ECU, not ingestion time)"
    },
    {
      "name": "ingested_utc",
      "type": "long",
      "doc": "Epoch ms when API received & validated event (IoT Hub timestamp)"
    },
    {
      "name": "lat",
      "type": "double",
      "doc": "Latitude (WGS84, precision 6 decimals = ~10cm)"
    },
    {
      "name": "lon",
      "type": "double",
      "doc": "Longitude (WGS84, precision 6 decimals = ~10cm)"
    },
    {
      "name": "speed_kmh",
      "type": "float",
      "doc": "Instantaneous speed (from ECU speedometer, smoothed)"
    },
    {
      "name": "heading_deg",
      "type": "float",
      "doc": "Bearing from true north (0-360 degrees)"
    },
    {
      "name": "gps_accuracy_m",
      "type": "float",
      "doc": "Reported accuracy (RMS error), input to Kalman R matrix"
    },
    {
      "name": "geo_hash",
      "type": "string",
      "doc": "H3 cell ID level 9 (~170m hexagon), partition key"
    },
    {
      "name": "is_jitter_van",
      "type": "boolean",
      "doc": "[Simulation only] Flag for faulty GPS units (10% of fleet)"
    },
    {
      "name": "is_friday_afternoon",
      "type": "boolean",
      "doc": "[Computed] True if dow=4 AND hour >= 14"
    },
    {
      "name": "schema_version",
      "type": "int",
      "doc": "Schema version (backward compat), current = 1"
    }
  ]
}
```

**Key Design Decisions:**
- `timestamp_utc` vs `ingested_utc`: Allows anomaly detection on stale data (>15 min gap = network issue)
- `geo_hash`: Partition key enables O(1) peer-van lookup via H3 k-ring (8-ring covers ~3km)
- `gps_accuracy_m`: Not post-validation; source ECU value, used in Kalman observation noise

### 4.2 Sensor Telemetry Schema

```json
{
  "type": "record",
  "name": "SensorTelemetry",
  "fields": [
    {
      "name": "event_id",
      "type": "string",
      "doc": "UUID v4"
    },
    {
      "name": "van_id",
      "type": "string",
      "doc": "Partition key"
    },
    {
      "name": "timestamp_utc",
      "type": "long",
      "doc": "Source timestamp on ECU"
    },
    {
      "name": "event_type",
      "type": {
        "type": "enum",
        "name": "SensorEventType",
        "symbols": ["HEARTBEAT", "ALERT"]
      },
      "doc": "HEARTBEAT: 5-sec cadence | ALERT: threshold breach"
    },
    {
      "name": "tyre_psi_min",
      "type": "float",
      "doc": "[PRE-COMPUTED at source] Minimum of 4 tyre pressure readings. Avoids array scan at 16 partitions × 1000 events/sec"
    },
    {
      "name": "engine_temp_c",
      "type": "float",
      "doc": "Engine coolant temperature (°C)"
    },
    {
      "name": "fuel_level_pct",
      "type": "float",
      "doc": "Fuel tank percentage (0-100)"
    },
    {
      "name": "health_score",
      "type": "float",
      "doc": "Composite OBD2 health (0-1), higher = healthier"
    },
    {
      "name": "alert_flags",
      "type": "int",
      "doc": "Bitmask: bit0=low_fuel, bit1=overtemp, bit2=low_oil, bit3=check_engine"
    },
    {
      "name": "safe_to_continue",
      "type": "boolean",
      "doc": "[PRE-COMPUTED at source] Boolean gate: if false, vehicle cannot be dispatched. Fallback agent reads 1 bool, not 5 fields"
    },
    {
      "name": "firmware_version",
      "type": "string",
      "doc": "ECU firmware version (e.g., '3.2.1'), used to select per-firmware anomaly model"
    },
    {
      "name": "schema_version",
      "type": "int",
      "doc": "Current = 1"
    }
  ]
}
```

**Key Design Decisions:**
- `tyre_psi_min` (pre-computed): Stream Analytics reads 1 float, not 4-element array
- `safe_to_continue` (pre-computed): Circuit breaker gate computed at source (lower latency, consistent across paths)
- `alert_flags` (bitmask): Smaller than boolean array; bitwise ops efficient on streams

### 4.3 Package Manifest Schema

```json
{
  "type": "record",
  "name": "PackageManifest",
  "fields": [
    {
      "name": "event_id",
      "type": "string"
    },
    {
      "name": "van_id",
      "type": "string",
      "doc": "Partition key"
    },
    {
      "name": "timestamp_utc",
      "type": "long",
      "doc": "When manifest state changed (LOADED/UNLOADED/PRIORITY_CHANGED)"
    },
    {
      "name": "event_type",
      "type": {
        "type": "enum",
        "name": "ManifestEventType",
        "symbols": ["LOADED", "UNLOADED", "PRIORITY_CHANGED"]
      }
    },
    {
      "name": "package_id",
      "type": "string",
      "doc": "Unique package identifier"
    },
    {
      "name": "priority_class",
      "type": {
        "type": "enum",
        "name": "PriorityClass",
        "symbols": ["LIFE_CRITICAL", "PREMIUM", "STANDARD"]
      },
      "doc": "LIFE_CRITICAL → LangGraph AI. Others → OR-Tools"
    },
    {
      "name": "delivery_sla_utc",
      "type": "long",
      "doc": "Deadline (epoch ms). Used as Redis sorted set score for SLA queries"
    },
    {
      "name": "time_to_sla_sec",
      "type": "int",
      "doc": "[PRE-COMPUTED at publish] Seconds from now to SLA. Avoids timestamp comparison in stream queries"
    },
    {
      "name": "dest_lat",
      "type": "double"
    },
    {
      "name": "dest_lon",
      "type": "double"
    },
    {
      "name": "dest_name",
      "type": "string",
      "doc": "Human-readable location (e.g., 'Hospital Central')"
    },
    {
      "name": "weight_kg",
      "type": "float",
      "doc": "Package weight, used for vehicle capacity checks in OR-Tools"
    },
    {
      "name": "requires_cold_chain",
      "type": "boolean",
      "doc": "True if temperature-sensitive (blood, vaccines). Flags vehicle climate control requirement"
    },
    {
      "name": "special_handling",
      "type": {
        "type": "array",
        "items": "string"
      },
      "doc": "Array of strings: ['FRAGILE', 'HAZMAT', 'COLD_CHAIN', 'PERISHABLE']"
    },
    {
      "name": "schema_version",
      "type": "int"
    }
  ]
}
```

**Key Design Decisions:**
- `priority_class`: Routes decision (AI vs OR-Tools) at ingestion, not later in pipeline
- `time_to_sla_sec` (pre-computed): No need for timestamp arithmetic in warm path
- `special_handling`: Array, but small (typically 1-2 items), allows flexible requirements

---

## 5. Conditional Flows: Variations & Edge Cases

### 5.1 Friday Afternoon Variance Handling

```
Detected: dow=4 AND hour >= 14 AND rolling_std_dev > 3× baseline

[Stream Analytics]
├─ Identifies: "Friday PM regime detected: std-dev 18.2 vs baseline 6.1 (3×)"
│
└─ Action: Tag all routes in affected zone with "high_variance_regime=true"

[LangGraph Agent receives manifest with high_variance flag]
│
├─ Standard logic: Minimize expected value (mean ETA)
│  ├─ Route A: ETA mean = 28 min
│  └─ Route B: ETA mean = 31 min → Choose A
│
├─ Friday PM logic: Minimize 90th percentile (P90 ETA)
│  ├─ Route A: ETA P90 = 35 min (high variance)
│  └─ Route B: ETA P90 = 33 min (more stable) → Choose B (unexpected!)
│
└─ Confidence: 0.91 (variance adds uncertainty)
     [Message to driver: "Friday traffic is unpredictable. Choosing stable route (3 min slower) to guarantee on-time delivery."]
```

### 5.2 Sensor Anomaly Handling

```
Anomaly detected: tyre_psi_min dropped from 32 → 28 (4 PSI, rapid change)
              + engine_temp spiked 85°C → 92°C
              + Isolation Forest score: -0.45 (very anomalous)

[Stream Analytics]
├─ gate 1: safe_to_continue = false (pre-computed at source)
│         [AND]
├─ gate 2: anomaly_detected = true
│         [AND]
├─ gate 3: confidence > 0.8
│
└─ Action: IMMEDIATE ALERT (bypass throttle)

[Dispatcher Dashboard]
├─ Red alert: "VAN-0042 — Tire pressure critical"
├─ Recommendation: "Divert to nearest repair facility (2 km, 8 min)"
├─ Driver notification: "Vehicle safety alert. Please pull over and call maintenance."
└─ Ops action: Phone call to driver (not in-app, too urgent)

[Result]
├─ Driver stops at tire shop
├─ Repair takes 25 min
├─ All pending deliveries on van rerouted to nearest backup vans
└─ SLA status: 3 packages now at risk → dispatcher handles manually
```

### 5.3 Network Delay Handling (Stale Data)

```
GPS event arrives with timestamp_utc = 2026-03-22T14:10:00Z
Ingested at Current time = 2026-03-22T14:25:30Z
             
Staleness = 15 min 30 sec (unusual!)

[Stream Analytics]
│
├─ Check: If (now - timestamp_utc) > 15 min → STALE DATA
│
├─ Action: Log anomaly, but continue processing
│
└─ Alert: "VAN-0042 GPS connectivity issue (15 min latency)"
   ├─ This might indicate network outage in zone (investigate)
   ├─ Use last good position from cache instead
   └─ Flag: reliability_score = 0.6 (reduced confidence for routing)

[Warm Path]
│
└─ LangGraph Agent sees reliability_score = 0.6
    ├─ Reduces confidence in ETA model
    ├─ Chooses more conservative route (shorter, less traffic-dependent)
    └─ Adds 5 min buffer to SLA recommendations
```

---

## 6. End-to-End Example: Van #402 Blood Delivery (Task 3 Scenario)

### Timeline

```
T=00:00 (Day 3, 14:00 UTC)
   Driver loads 3× blood units O- at Lab A
   dispatch_event = LOADED(priority="LIFE_CRITICAL", sla=14:30)
        │
        ▼

T=00:02 (14:02)
   PackageManifest event on Event Hub topic
   LangGraph Agent invoked
        │
        ├─ Check sensor state
        │  └─ safe_to_continue = true ✓
        │
        ├─ Check van #42 history
        │  └─ Last service: 2026-03-10 (healthy)
        │
        ├─ Search routes
        │  └─ Route A (south_ring): 12 km, 28 min ETA
        │
        ├─ Predict ETA
        │  └─ dow=1 (not Friday), hour=14 → standard model → 28 min ✓
        │
        └─ Approve
           └─ "ETA 28 min << SLA 30 min. Confident: 0.96"
        │
        ▼

T=00:05 (14:05)
   Driver notification: "Go to Hospital Central via south_ring. ETA 14:33."
   Driver starts navigation
        │
        ▼

T=06:30 (14:11:30)
   Van in transit on south_ring
   GPS telemetry streaming (5-sec cadence)
   Hot path processes Kalman filter → CLEAN SIGNAL ✓
        │
        ▼

T=07:20 (14:12:20)
   GPS event arrives: lat=19.050, lon=72.891 (15% into journey)
   Kalman smoothing → covariance=0.0003 (very smooth, no jitter)
        │
        ▼

T=10:00 (14:15)
   Sensor event: tyre_psi_min=28.5 (down from 32, slow leak?)
   Anomaly score = -0.32 (borderline)
   BUT safe_to_continue = true (no alert threshold breach)
        │
        └─ Log to audit, continue monitoring
        │
        ▼

T=20:00 (14:25)
   Van approaching destination
   GPS: lat=19.0156, lon=72.8295 (Hospital Central)
   Current speed = 3 km/h (parking lot entry)
        │
        ▼

T=22:00 (14:27)
   ✅ DELIVERY COMPLETE
   Driver confirms delivery via app
   Audit log updated:
   ├─ decision_id: "DECISION-2026-03-22-042-001"
   ├─ actual_delivery_time_min: 27
   ├─ sla_promise_min: 30
   ├─ outcome: "EARLY_SUCCESS"
   ├─ any_incidents: false
   └─ confidence_vs_actual: 0.96 prediction ≈ 27 actual → ACCURATE ✓
```

---

## 7. Schema Validation & Error Handling

### Validation Rules (Avro + Custom Checks)

```python
def validate_gps_telemetry(event):
    """Validation gates before Event Hub acceptance."""
    
    # Avro schema validation (automatic)
    # ✓ Type checks: lat float, lon float, speed float
    # ✓ Required fields present
    
    # Custom business logic
    assert -90 <= event.lat <= 90, "Latitude out of bounds"
    assert -180 <= event.lon <= 180, "Longitude out of bounds"
    assert 0 <= event.heading_deg <= 360, "Heading invalid"
    assert event.gps_accuracy_m > 0, "Accuracy must be positive"
    assert event.timestamp_utc <= now() <= now() + 10, "Timestamp in future (clock skew)"
    
    # Check staleness
    staleness_sec = (now() - event.timestamp_utc) / 1000
    if staleness_sec > 900:  # 15 min
        log_warning(f"Stale GPS: {staleness_sec}s old")
        event.reliability_score = 0.5
    
    return event  # Passed validation
```

### Error Handling: Malformed Event

```
Event arrives with lon="not_a_float"

[API Gateway]
├─ Avro deserialization fails
├─ Response: 400 Bad Request
│  {
│    "error": "schema_validation_failed",
│    "message": "lon: expected float, got string",
│    "event_id": "xyz-123"
│  }
└─ Event rejected, not written to Event Hub

[Metrics]
└─ validation_failures_total{domain="gps"} += 1
```

---

## 8. Quick Reference: When Flows Change Course

| Condition | Hot Path | Warm Path | Action |
|-----------|----------|-----------|--------|
| **Jitter detected** | ✓ | — | Flag, monitor, continue routing |
| **Sensor anomaly + safe_to_continue=false** | ✓ | —GATE— | HOLD, reroute, dispatcher alerted |
| **LIFE_CRITICAL manifest** | — | ✓ LangGraph | AI decision (not OR-Tools) |
| **Friday PM high variance** | — | ✓ MODE | Switch to P90-minimize objective |
| **ETA drift >10% + buffer <10min** | — | ✓ RECOMPUTE | Evaluate alternative routes in real-time |
| **Stale GPS (>15 min)** | ⚠️ | ⚠️ | Reduce confidence scores |
| **Network failure on IoT Hub** | — | FALLBACK | Use cached route, manual dispatch |

---

**Document Version:** 1.0  
**Last Updated:** 2026-03-22  
**Related:** [ARCHITECTURE.md](ARCHITECTURE.md) | [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) | [TECH_STACK.md](TECH_STACK.md)
