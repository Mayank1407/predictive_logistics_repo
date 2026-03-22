# AGENTS.md — Predictive Logistics Engine

This file provides context for AI coding assistants (GitHub Copilot, Claude, Cursor) working in this repository.

## What this system does

A real-time intelligent fleet management system for 5,000 delivery vans across Mumbai. Replaces static daily routes with dynamic, AI-driven decisions. Processes 3,000+ events/sec and delivers route updates to drivers in under 30 seconds.

## Tech stack

| Layer | Technology | Role |
|---|---|---|
| Edge | Azure IoT Hub, API Management | Device ingestion, auth, TLS |
| Stream | Azure Event Hubs (Kafka API) | 3-topic message bus, 32/16/8 partitions |
| Hot path | Azure Stream Analytics | Sensor anomaly detection, <2s latency |
| Warm path | AKS + OR-Tools | Route optimisation, <30s latency |
| Cold path | Databricks DLT + MLflow | Model retraining, feature engineering |
| AI agents | LangGraph + LangSmith | Life-critical decision reasoning |
| ML models | XGBoost, Isolation Forest, Kalman Filter | ETA prediction, anomaly detection, GPS smoothing |
| Storage | Cosmos DB, Redis, ADX, Delta Lake | Van state, route cache, telemetry, ML features |
| Notifications | Azure Notification Hubs → APNs/FCM | Driver push, 2/hr throttle |

## Repository structure

```
notebooks/   — 3 Colab notebooks (data generation, algorithms, business results)
data/        — Simulation scripts + sample CSVs (100 vans, 7 days, Mumbai)
schemas/     — Avro schemas for all 3 Event Hub topics
docs/        — Architecture documentation
```

## The three event streams

### GpsTelemetry (partition key: geo_hash H3 L9)
- 5-second cadence, 32 partitions
- Key fields: van_id, lat, lon, geo_hash, speed_kmh, heading_deg, gps_accuracy_m, schema_version
- geo_hash enables O(1) peer-van lookup via H3 k-ring — no cross-partition joins

### SensorTelemetry (partition key: van_id)
- 5-second cadence + threshold breach, 16 partitions
- Key fields: tyre_psi_min (pre-computed), alert_flags (bitmask), safe_to_continue (pre-computed bool), health_score
- tyre_psi_min: pre-computed min of 4 tyres — Stream Analytics reads 1 field not array at 1000 events/sec
- safe_to_continue: pre-computed by hot path → written to Redis — fallback agent reads 1 field

### PackageManifest (partition key: van_id)
- On state change only (LOADED/UNLOADED/PRIORITY_CHANGED), 8 partitions
- Key fields: priority_class (LIFE_CRITICAL/PREMIUM/STANDARD), delivery_sla_utc (Redis sorted set score), time_to_sla_sec (pre-computed)
- priority_class routes to LangGraph (LIFE_CRITICAL) or OR-Tools (others)

## Coding conventions

- Python: type hints, docstrings, numpy-style array operations
- No magic numbers — use named constants (JITTER_THRESHOLD_M = 40.0)
- All timestamps in epoch milliseconds (int64) — never datetime strings in schemas
- Pre-compute expensive fields at publish time (tyre_psi_min, safe_to_continue, time_to_sla_sec)
- Bitmasks preferred over boolean arrays for alert flags in stream processing
- H3 level 9 (~170m hexagons) for spatial indexing — not Geohash (unequal distances)

## Algorithm notes

### Kalman Filter (GPS jitter detection)
- State: [lat, lon] — 2D position
- Observation noise R = (gps_accuracy_m / 111000)² — scaled by reported accuracy
- High covariance output → likely GPS noise. Low covariance + near-zero speed → genuine stall

### Isolation Forest (sensor anomaly)
- contamination=0.05 (5% anomaly rate expected)
- Features: tyre_psi_min, engine_temp_c, fuel_level_pct, speed_kmh, health_score
- Trained per firmware_version — different baseline per ECU type

### XGBoost ETA model
- Features: hour, dow, is_friday, fri_pm_flag, speed_kmh, speed_lag1, speed_lag2, heading_deg
- Friday regime: if rolling std-dev in H3 zone > 3× baseline, switch objective to minimise P90 ETA
- Served from MLflow on AKS, <50ms inference latency

### 3-Signal GPS ensemble
- Signal 1: Kalman covariance > 75th percentile → jitter candidate
- Signal 2: Heading coherence score < 0.4 → jitter candidate
- Signal 3: gps_accuracy_m > 40 → jitter candidate
- Classification: JITTER if 2 of 3 signals agree

## What the AI should NEVER do

- Never use raw ADO.NET or direct SQL in application code — use repositories
- Never put business logic in stream queries — logic belongs in AKS services
- Never store secrets in code — use Azure Key Vault references
- Never route LIFE_CRITICAL packages through the standard OR-Tools path — always LangGraph
- Never drop driver update notifications — queue them, respect the 2/hr throttle
- Never trust a sensor reading with timestamp_utc more than 15 minutes stale
