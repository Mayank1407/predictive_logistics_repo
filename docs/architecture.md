# Architecture — Predictive Logistics Engine

## System overview

Real-time intelligent fleet management for 5,000 delivery vans across Mumbai. Three-plane architecture: Ingestion → Intelligence → Action.

## Three-plane design

### Plane 1 — Ingestion
All data enters through a secure gateway before touching any processing layer.

```
Van GPS unit (NMEA)     → Azure IoT Hub (MQTT)     → Schema Registry → Event Hubs: gps_telemetry
Van ECU (OBD-II/TPMS)  → Azure IoT Hub (AMQP)     → Schema Registry → Event Hubs: sensor_telemetry
Driver mobile app       → Azure API Management     → Schema Registry → Event Hubs: package_manifest
Dispatch portal         → Azure API Management     → Backend APIs
```

**Throughput:** 5,000 vans × 3 streams × 5-sec cadence = ~3,000 events/sec peak
**Event Hubs sizing:** 20 Throughput Units, auto-inflate to 40 on spike

### Plane 2 — Intelligence (three latency tiers)

| Path | Technology | Latency SLA | Purpose |
|---|---|---|---|
| Hot | Azure Stream Analytics | < 2 seconds | Sensor anomaly detection, life-critical alerts, geofence breach |
| Warm | AKS + OR-Tools + XGBoost | < 30 seconds | Route optimisation, ETA prediction, driver notifications |
| Cold | Databricks DLT + MLflow | Minutes–hours | Model retraining, pattern learning, feature engineering |

### Plane 3 — Action
```
Dispatcher alerts    → SignalR push to Angular portal (< 10 sec SLA)
Driver updates       → Azure Notification Hubs → APNs/FCM → React Native (< 30 sec, max 2/hr)
Operations dashboard → Azure Data Explorer (KQL) + Power BI
```

## Data flow (Van #402 scenario — 30-second clock)

```
T+0s   Van ECU detects 5 PSI drop on FL tyre
        → MQTT message to Azure IoT Hub
        → Avro validation in Schema Registry
        → Event Hubs: sensor_telemetry, partition=VAN-0042

T+1s   Azure Stream Analytics 5-sec tumbling window
        → tyre_psi_min field read (pre-computed — single float, no array scan)
        → alert_flags bitmask: flags & 2 > 0 = tyre warning
        → Isolation Forest anomaly score > threshold → HIGH_RISK

T+2s   LangGraph agent activated (AKS pod)
        Node 1: Risk classifier → blowout probability from PSI drop rate + speed
        Node 2: Cargo check → Redis ZRANGEBYSCORE priority:van:VAN-0042
                 → LIFE_CRITICAL package found, time_to_sla_sec = 892 (14 min 52 sec)
        Node 3: Constraint solver → compare blowout window vs SLA window
                 → safe_to_continue = true at current speed
        Node 4: Action dispatch → complete delivery then divert to garage
        → LangSmith trace written (full reasoning chain, auditable)

T+5s   Redis + Cosmos DB lookups complete
        → route:van:VAN-0042 → current waypoints and ETA
        → geo:garages GEORADIUS → nearest garage 0.8km post-delivery
        → New route computed: current_pos → delivery_dest → garage

T+10s  Dispatcher P0 alert
        → AKS notification service builds payload
        → SignalR push to Angular dispatch portal
        → Payload: van_id, incident_type, decision_taken, time_to_SLA, recommended_action

T+28s  Throttle service check
        → Redis ZCOUNT driver:updates:{driver_id} last 3600 sec = 0
        → LIFE_CRITICAL bypass flag also active
        → Notification dispatcher builds push payload with new waypoints

T+30s  Driver receives route update
        → Azure Notification Hubs fans out to FCM (Android) / APNs (iOS)
        → React Native app wakes, updates map, TTS voice prompt
        → Route cached in SQLite for offline resilience
        → Delivery receipt written to Azure Data Explorer
```

## High availability design

### Rerouting engine (AKS)
```
Primary region:    Zone-redundant node pools, 3 replicas, HPA, Istio circuit breaker
Secondary region:  Hot standby, pre-warmed, Traffic Manager priority failover
RTO:               < 30 seconds (secondary takes over)
RPO:               0 (Event Hub replay on recovery)
```

### Degraded mode (both regions unavailable)
```
Layer 1: Redis route cache — last computed route per van (TTL 90 min)
Layer 2: fallback_direct_path — pre-computed straight-line to destination
Layer 3: LIFE_CRITICAL packages: always served regardless of degradation level
Recovery: On restart, replay Event Hub from last committed offset, recompute all stale routes
```

## Schema design decisions

### GPS: geo_hash as partition key (not van_id)
Vans in the same area of Mumbai land on the same Event Hub partition. This enables peer-van GPS corroboration lookups without cross-partition joins — the jitter detection algorithm reads neighbouring vans via H3 k-ring(1) on the same partition.

If we partitioned by van_id, a jitter lookup for VAN-0042 would need to scan all 32 partitions to find nearby vans. With geo_hash, it's a single-partition lookup.

### tyre_psi_min: pre-computed minimum
The raw schema has tyre_psi[4] — an array of 4 floats. Stream Analytics processes this at 1,000 events/sec. Computing min(array) in the stream query adds latency and increases query complexity. Publishing tyre_psi_min as a pre-computed field at the source (ECU firmware) reduces hot-path latency and simplifies the Stream Analytics query to a single float comparison.

### alert_flags: bitmask over booleans
Four separate boolean fields (tyre_warning, engine_warning, fuel_low, overheat) would require four conditional checks in Stream Analytics. A bitmask collapses this to one bitwise AND: `alert_flags & 2 > 0 = tyre warning`. Simpler query, lower latency, smaller message size.

### delivery_sla_utc as Redis sorted set score
The manifest stream writes each package to Redis: `ZADD priority:van:{van_id} {delivery_sla_utc} {package_id}`. Because the score IS the SLA deadline epoch, `ZRANGEBYSCORE 0 {now+600000}` returns all packages due in the next 10 minutes in deadline order — a single O(log N) query. The fallback agent uses this to prioritise deliveries without the rerouting engine.

### time_to_sla_sec: pre-computed at publish time
LangGraph's constraint solver runs inside a 2-second hot-path window. Computing `(delivery_sla_utc - current_time) / 1000` at decision time introduces timestamp dependency and potential clock skew. Pre-computing at publish time and reading directly eliminates arithmetic inside the critical path.

## Redis key space

| Key pattern | Type | TTL | Written by | Read by |
|---|---|---|---|---|
| `route:van:{van_id}` | Hash | 90 min | Rerouting engine | Fallback agent, driver app |
| `health:van:{van_id}` | Hash | 15 min | Stream Analytics hot path | Rerouting engine, fallback agent |
| `priority:van:{van_id}` | Sorted Set (score=SLA epoch) | 2 hrs | Manifest service | LangGraph, fallback agent |
| `geo:garages` | GEO | 24 hrs | Ops data pipeline | LangGraph (GEORADIUS) |
| `driver:updates:{driver_id}` | Sorted Set | 1 hr rolling | Throttle service | Throttle service (ZCOUNT) |
| `fallback:decisions` | List | 48 hrs | Fallback agent | Recovery reconciliation → ADX |

## Algorithms

### OR-Tools CVRPTW (warm path routing)
- Capacitated VRP with Time Windows
- Warm-started from previous solution every 30-second cycle
- 5,000 vans clustered by H3 hex zone — each cluster solved in parallel on AKS pods
- Cost function switches on Friday 14:00–19:00: minimise P90 ETA (not mean ETA)
- Regime flag published by Databricks Feature Store when zone std-dev > 3× baseline

### Kalman Filter (GPS jitter, Signal 1 of 3)
- State vector: [lat, lon]
- Observation noise R = (gps_accuracy_m / 111000)² per reading
- High uncertainty covariance → likely GPS noise
- Low covariance + near-zero speed → genuine traffic stall

### Isolation Forest (sensor anomaly)
- contamination=0.05
- Features: tyre_psi_min, engine_temp_c, fuel_level_pct, speed_kmh, health_score
- Trained per firmware_version — ECU baseline varies by van model and firmware
- Score < threshold at 1,000 events/sec → hot path alert fires

### XGBoost ETA prediction
- 90-day rolling training window via Databricks DLT
- Features: hour, dow, is_friday, fri_pm_flag, speed_kmh, speed_lag1, speed_lag2, heading_deg, H3 zone
- Model served from MLflow on AKS, <50ms inference
- Weekly retraining — Friday patterns evolve with events and seasons

### 3-Signal GPS ensemble
```
Signal 1: Kalman covariance > P75 threshold     → jitter candidate
Signal 2: Heading coherence score < 0.4          → jitter candidate
Signal 3: gps_accuracy_m > 40                    → jitter candidate

Result: JITTER if 2 of 3 signals agree
        TRAFFIC STALL if 2 of 3 disagree

Rationale: A single broken sensor (faulty accuracy chip, one bad heading reading)
           cannot trigger a false alert. Requires corroboration across independent signals.
```
