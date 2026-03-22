# System Architecture — Predictive Logistics Engine

## Overview

Real-time intelligent fleet management system processing 3,000+ events/sec across 5,000 delivery vans in Mumbai. Sub-30-second route update latency with AI-driven decision-making for life-critical shipments.

## High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        EDGE LAYER                               │
│  Azure IoT Hub + API Management (TLS, Auth, Rate Limiting)     │
└────────────────────────┬────────────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          │              │              │
    (5 vans/sec)   (16 per/sec)   (2 events/sec)
          │              │              │
      GPS (32p)      Sensor (16p)  Manifest (8p)
          │              │              │
        ┌─┴──────────────┴──────────────┴─┐
        │  Azure Event Hubs (Kafka API)   │
        │  3-topic message bus, 56p total │
        └─────────────────┬────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
        ▼                 ▼                 ▼
   [HOT PATH]        [WARM PATH]       [COLD PATH]
   <2s latency       <30s latency      Batch mode
        │                 │                 │
        │                 │                 │
   Stream Analytics    AKS Cluster      Databricks
   - Jitter detect     - OR-Tools       - DLT Pipeline
   - Anomalies        - Route optim     - MLflow retraining
   - GPS smoothing    - LangGraph AI    - Feature engineering
        │                 │                 │
        │                 │                 │
        └────────┬────────┴────────┬────────┘
                 │                 │
            ┌────▼─────────────────▼────┐
            │   Data Layer              │
            │ - Cosmos DB (van state)   │
            │ - Redis (route cache)     │
            │ - ADX (telemetry)         │
            │ - Delta Lake (features)   │
            └────┬──────────────────────┘
                 │
         ┌───────┴────────┐
         │                │
    [DRIVER APP]    [OPERATIONS DASHBOARD]
    Push notifs     Real-time visibility
    Route updates   Anomaly alerts
```

## Layered Architecture

### 1. **Edge Layer** — Device Ingestion & Auth
- **Azure IoT Hub**: Device identity, TLS termination, message routing
- **API Management**: Rate limiting (5 msg/van/sec), auth enforcement
- **Partition Routing**: H3 geohash distribution for geographic load balancing

**SLA:** 99.95% availability, sub-500ms ingestion latency

### 2. **Stream Layer** — Message Bus (Azure Event Hubs)
Three independent topics with Kafka-compatible API:

#### Topic: `gps-telemetry` (32 partitions)
- **Partition Key:** H3 geohash L9 (~170m hexagons)
- **Cadence:** 5-second heartbeat or on heading change > 10°
- **Retention:** 7 days
- **Fields:** van_id, lat, lon, speed_kmh, heading_deg, gps_accuracy_m, geo_hash, schema_version

#### Topic: `sensor-telemetry` (16 partitions)
- **Partition Key:** van_id
- **Cadence:** 5-second + threshold breach events
- **Retention:** 30 days (cold path ingestion)
- **Pre-computed Fields:** tyre_psi_min (4→1 field), safe_to_continue (bool), health_score

#### Topic: `package-manifest` (8 partitions)
- **Partition Key:** van_id
- **Trigger:** State change only (LOADED/UNLOADED/PRIORITY_CHANGED)
- **Retention:** 90 days
- **Fields:** priority_class (enum), delivery_sla_utc, time_to_sla_sec (pre-computed)

**Design Rationale:**
- Partition distribution prevents join operations across shards
- Pre-computed fields reduce stream query complexity
- Bitmasks for alert flags reduce message size

### 3. **Hot Path** — Real-Time Anomaly Detection (< 2s latency)
**Technology:** Azure Stream Analytics (Kinetic Units, not throughput units)

#### Stream Job 1: GPS Jitter Detection
```
Input: gps-telemetry
Process:
  1. Kalman filter on [lat, lon] per van (5-step window)
  2. Detect covariance > 75th percentile
  3. Cross-reference with H3 k-ring peers (8-ring search)
  4. Output: JITTER / STALL / NORMAL classification
Output: Redis (kv: van_id→{jitter_score, peers_agree})
```

#### Stream Job 2: Sensor Anomaly Detection
```
Input: sensor-telemetry
Process:
  1. Isolation Forest (pre-fitted model per firmware_version)
  2. Compute anomaly_score = -predict(X)
  3. Safe-to-continue callback (gate function)
Output: Redis + Cosmos DB (state append)
```

**Failure Mode:** On stream analytics failure:
- Last 30 seconds of state preserved in Redis
- Fallback agent reads `safe_to_continue` boolean (pre-computed at publish)

### 4. **Warm Path** — Route Optimization (< 30s latency)
**Technology:** AKS (3 node cluster, auto-scaling)

#### Microservice 1: OR-Tools Router
```python
Input:
  - Current van position (from Redis cache)
  - Remaining packages (from Cosmos DB)
  - Road network graph (loaded on startup)
  - Time window constraints (delivery SLA)

Output:
  - Optimized routing waypoints
  - ETA per package
  - Fuel recommendation

Objective Function:
  - Minimize total distance (standard)
  - Minimize P90 ETA on Fridays (regime detection)
  - Hard constraint: time-window violations < 2%
```

**Deployment:** 
- 3 replicas (round-robin on van_id % 3)
- gRPC interface (10ms latency vs 50ms REST)
- Model reloads: daily 02:00 UTC

#### Microservice 2: LangGraph AI Agent (Life-Critical Path)
```
Only for priority_class == LIFE_CRITICAL

Agent State:
  - Van ID, location, manifest
  - Historical delivery success rate
  - Weather, traffic, sensor alerts

Tools:
  - Route searcher (same network graph)
  - ETA predictor (XGBoost model)
  - Anomaly context (Cosmos DB lookup)
  - Driver communication (notification queue)

Decision: 
  Route approval → Queue to driver
           │
           ├─ Hold (sensor anomaly detected)
           │
           └─ Reroute (traffic jam → alternate pickup)

TModel:** gpt-4-turbo (fallback: gpt-3.5-turbo)
Latency SLA: < 15 seconds decision time
```

### 5. **Cold Path** — ML Retraining (Batch, 24h cycle)
**Technology:** Databricks DLT + MLflow

#### Feature Engineering Pipeline
```
Input: ADX telemetry (7-day window)

Features:
  1. Time-domain: hour, dow, is_friday, fri_pm_flag
  2. Speed-domain: mean, std, lag1, lag2, percentiles
  3. Location-domain: H3 z-order curve, route_id
  4. Sensor-domain: tyre_health, engine_temp, anomaly_count
  5. Delivery-domain: package_class, sla_buffer_min

Output: Delta Lake table (Parquet partitioned by date)
```

#### XGBoost ETA Model
```
Target: travel_time_min per segment

Training:
  - Historical 30 days of GPS + manifest data
  - Cross-validation: stratified by dow, H3 zone
  - Hyperparameters tuned on Friday high-variance regime

Objective:
  - Standard traffic: minimize MAE
  - Friday PM (detected): minimize P90 (quantile loss)

Registry: MLflow (versioning, stage promotion)
Serving: AKS sidecar endpoint (<50ms inference)
```

#### Isolation Forest (Sensor Anomaly)
```
Contamination: 5% (tuned on historical incident rate)
Per firmware_version: separate models
Retrain: weekly (Fridays 03:00 UTC)
Features: [tyre_psi_min, engine_temp_c, fuel_level_pct, speed_kmh, health_score]
```

## Data Flow Example: Life-Critical Package

```
Van #0042 loads 3x blood samples (LIFE_CRITICAL)
│
├─ PackageManifest event → Event Hub topic: package-manifest
│  ├─ priority_class: LIFE_CRITICAL
│  ├─ delivery_sla_utc: 2026-03-22T15:30:00Z
│  └─ time_to_sla_sec: 1800
│
├─ LangGraph Agent triggered (< 5sec)
│  ├─ Check van #0042 sensor state: "healthy" ✓
│  ├─ Check traffic: Friday 14:20 PM → high variance regime
│  ├─ XGBoost ETA inference: 32 min → within SLA ✓
│  ├─ Approval: ROUTE_APPROVED
│  └─ Output to Notification Hub (queue, throttle 2/hr)
│
├─ Driver receives: "3 blood samples, hospital route, ETA 14:52"
│
├─ Van in transit
│  ├─ GPS telemetry: 5/sec → Kalman filter (no jitter)
│  ├─ Sensor telemetry: safe_to_continue = true
│  └─ All nominal
│
├─ Delivery SLA met ✓
│  └─ Audit logged to Cosmos DB
```

## Consistency & Resilience

### Event Sourcing
- Immutable event log in Event Hubs (7-day retention)
- Cosmos DB: latest van state (TTL 30 days for archive)
- Redis: ephemeral cache (TTL 5 min on route, 10 sec on sensor cache)

### Circuit Breaker Pattern
```
Route Optimization Unavailable?
  ├─ Fallback 1: Cache previous route (< 1 min old)
  ├─ Fallback 2: Simple greedy algorithm (distance-based)
  └─ Fallback 3: Manual dispatch (ops dashboard)
```

### Idempotency
- Driver update notification: keyed on (van_id, route_hash, timestamp)
- Duplicate checks: 5-minute window
- Throttle: max 2 notifications/van/hour

## Monitoring & Observability

### Key Metrics
- **Latency:** P50, P95, P99 per stream job
- **Throughput:** events/sec per topic
- **Jitter Detection Accuracy:** F1 score on validation set
- **Route SLA Compliance:** % deliveries within time window
- **Anomaly Detection:** precision, recall per sensor type
- **AI Agent Response Time:** histogram of decision latency

### Alerts
- Stream Analytics backlog > 10s
- Hot path latency > 5s
- Route optimization failure rate > 1%
- Sensor anomaly false-positive rate > 10%

## Deployment Strategy

- **Blue-Green:** Route optimization microservices (0-downtime)
- **Canary:** AI agent model updates (10% → 50% → 100%)
- **Rolling:** Stream Analytics (jobless deploy, state preserved)

---

**Document Version:** 1.0  
**Last Updated:** 2026-03-22  
**Owner:** Predictive Logistics Team
