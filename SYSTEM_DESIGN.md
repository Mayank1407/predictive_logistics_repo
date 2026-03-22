# System Design Deep Dive

## Design Principles

### 1. **Safety First (Life-Critical Path)**
- Never drop a decision on life-critical shipments; default to HOLD if uncertain
- Sensor anomalies are circuit breakers (immediate vehicle diversion)
- AI decisions always include confidence scores & alternatives

### 2. **Observability Over Correctness**
- Log every decision (even wrong ones) for post-mortem learning
- Trace IDs propagate through all systems (Event Hub → Stream → Router → API)
- Metrics emit at source (not aggregated); let observability tool decide

### 3. **Graceful Degradation**
- Sub-system failures don't cascade; fallback algorithms are always available
- Cache previous good state (route cache TTL 5 min on Redis)
- No synchronous dependencies between hot/warm/cold paths

### 4. **Latency Budget**
```
Total SLA: < 30 seconds (manifest → driver notification)
├─ Stream processing: < 2 sec (hot path)
├─ Decision logic: < 15 sec (warm path)
├─ Notification dispatch: < 2 sec (push to APNs/FCM)
└─ Network margin: < 11 sec
```

---

## Partition Strategy

### Why H3 Geohashing for GPS?

**Problem:**  
Naive partition key (van_id) causes joins across partitions for spatial queries (find peers in 1km radius).

**Solution: H3 Geohash L9**
- ~170m hexagons → captures 10-20 vans per hex in Mumbai
- 8-ring k-ring search → covers ~3km radius
- **O(1) peer lookup** without cross-partition joins

```python
from h3 import h3

def peer_vans_in_radius(lat, lon, radius_m=1000):
    """Find vans within radius without joins."""
    # Convert to H3 cell
    cell = h3.latlng_to_cell(lat, lon, 9)
    
    # Get all neighbors (8-ring = ~3km)
    neighbors = h3.grid_ring(cell, k=8)
    
    # Query Redis: per-cell van list (pre-computed by hot path)
    peers = []
    for neighbor_cell in neighbors:
        peers.extend(redis.smembers(f"h3:{neighbor_cell}:vans"))
    
    return peers[:20]  # Max 20 peer vans
```

### Why 3 Separate Topics?

| Aspect | Benefit |
|--------|---------|
| **Partition Independence** | GPS jitter doesn't clog sensor anomaly detection |
| **Retention Policies** | Sensor archived 30d (cold ML features); GPS only 7d (real-time) |
| **Consumer Scaling** | Route optimizer pulls manifests (low volume, <2/sec), unpressured |
| **Failure Isolation** | GPS telemetry backlog doesn't block route decisions |

---

## State Machine: Van Delivery Lifecycle

```
IDLE
  │
  ├─ Driver loads manifest
  │   └─ Event: PackageManifest (priority_class=LIFE_CRITICAL)
  │
  LOADING
    │
    ├─ [Check sensor_state]
    │   ├─ safe_to_continue=false → HOLD_FOR_MAINTENANCE
    │   └─ safe_to_continue=true → continue
    │
    └─ [Submit to AI agent if LIFE_CRITICAL]
        ├─ Decision=HELD → WAITING_DISPATCHER_APPROVAL
        ├─ Decision=REROUTED → REROUTE_IN_PROGRESS
        └─ Decision=APPROVED → continue
        
  IN_TRANSIT
    │
    ├─ [Continuous monitoring]
    │   ├─ Sensor anomaly detected → ALERT_DRIVER, continue (unless critical)
    │   ├─ GPS jitter + traffic → log, continue
    │   ├─ ETA drift > 10% → recompute route
    │   └─ Time-to-SLA < 5 min → PRIORITY_ROUTE
    │
    └─ [At waypoint]
        ├─ Confirm arrival (driver tap)
        └─ Continue to next
  
  DELIVERED
    │
    └─ Audit log entry (latency, route actual vs predicted, incidents)
```

---

## Decision Trees

### GPS Jitter Classification (3-Signal Ensemble)

```python
def classify_jitter(van_id, gps_reading):
    """3-signal majority vote: JITTER if >=2 signals agree."""
    
    # Signal 1: Kalman Covariance
    kalman_cov = get_kalman_covariance(van_id)
    signal1 = kalman_cov > np.percentile(historical_cov, 75)
    
    # Signal 2: Heading Coherence
    headings = get_last_5_headings(van_id)
    heading_std = np.std(headings)
    signal2 = heading_std > 45  # Degrees (threshold)
    
    # Signal 3: Reported GPS Accuracy
    signal3 = gps_reading.accuracy_m > 40
    
    # Majority vote
    votes = sum([signal1, signal2, signal3])
    
    if votes == 3:
        return "DEFINITE_JITTER", confidence=0.99
    elif votes == 2:
        return "LIKELY_JITTER", confidence=0.85
    elif votes == 1:
        return "AMBIGUOUS", confidence=0.50
    else:
        return "CLEAN_SIGNAL", confidence=0.95
```

### SLA Risk Assessment

```python
def assess_sla_risk(manifest_id, current_van_state):
    """
    Returns: (risk_level, time_buffer_sec, action_code)
    """
    time_to_sla = manifest.delivery_sla_utc - now()
    eta_to_delivery = estimate_eta(van_state)
    
    buffer_sec = time_to_sla - eta_to_delivery
    
    if buffer_sec < -1800:  # >30 min overdue
        return ("CRITICAL_BREACH", buffer_sec, "ESCALATE_TO_OPS")
    elif buffer_sec < 300:   # <5 min buffer
        return ("CRITICAL_RISK", buffer_sec, "PRIORITY_ROUTE")
    elif buffer_sec < 900:   # <15 min buffer
        return ("AT_RISK", buffer_sec, "RECOMPUTE_ROUTE")
    else:
        return ("ON_TRACK", buffer_sec, None)
```

---

## Friday Regime Detection (XGBoost Adaptation)

### Problem

Friday 2-6 PM: Traffic variance explodes (+400% std-dev). Model trained on standard deviation now underestimates P90 ETA.

### Solution

```python
def detect_friday_regime(dow: int, hour: int, zone_h3: str) -> bool:
    """
    Check if current zone is in Friday high-variance regime.
    Adaptive objective: minimize P90 ETA instead of MAE.
    """
    
    if dow != 4:  # Not Friday
        return False
    
    if hour < 14 or hour >= 19:  # Outside 2-7 PM
        return False
    
    # Check rolling std-dev in this H3 zone over last 60 minutes
    speeds_60min = adx.query_segment_speeds(zone_h3, timedelta(minutes=60))
    rolling_std = np.std(speeds_60min)
    
    # Compare to baseline (Monday 2-6 PM)
    baseline_std = get_baseline_zone_std(zone_h3, dow=0, hour=hour)
    
    regime_spike = rolling_std / baseline_std
    
    return regime_spike > 3.0  # 3× normal variance = regime change
```

### Training Strategy

```python
# XGBoost has quantile loss objective
model = xgb.XGBRegressor(
    # Standard traffic
    objective='reg:squarederror',  # Minimize MSE
    
    # OR Friday PM (detected at inference)
    objective='reg:quantileerror',  # Minimize P90
    quantile_alpha=0.9  # 90th percentile target
)

# At inference:
if detect_friday_regime(dow, hour, zone):
    # Use model trained with quantile loss
    eta_pred = model_friday.predict(features)
else:
    # Use standard model
    eta_pred = model_standard.predict(features)
```

---

## Isolation Forest: Sensor Anomaly Detection

### Per-Firmware Model Ensemble

Different ECU firmware versions have **different baseline signatures**. E.g., firmware v2.1 reports engine temp 2°C higher than v3.2 for same vehicle state.

```python
@lru_cache(maxsize=50)
def get_anomaly_detector(van_id):
    """Load model per firmware version, not per van."""
    van = get_van_metadata(van_id)
    firmware_version = van.firmware_version  # e.g., "3.2.1"
    
    model = load_model_from_vault(
        f"isolation-forest:sensor:{firmware_version}:prod"
    )
    return model

def detect_sensor_anomaly(van_id, sensor_reading):
    model = get_anomaly_detector(van_id)
    
    features = np.array([
        sensor_reading.tyre_psi_min,
        sensor_reading.engine_temp_c,
        sensor_reading.fuel_level_pct,
        sensor_reading.speed_kmh,
        sensor_reading.health_score
    ]).reshape(1, -1)
    
    anomaly_score = model.score_samples(features)[0]
    is_anomalous = model.predict(features)[0] == -1  # -1 = outlier
    
    return {
        "is_anomalous": is_anomalous,
        "anomaly_score": anomaly_score,  # Negative = more anomalous
        "contamination_expected": 0.05  # 5% expected rate
    }
```

### Retraining Schedule

```yaml
# Weekly retraining on Fridays, 03:00 UTC
training_job:
  schedule: "0 3 * * 5"  # Fridays 3 AM
  data_window: "7 days"
  
  per_firmware:
    - version: "3.2.1"
      sample_vans: 500  # Use 500 vans from this firmware
      min_samples: 50000  # Min telemetry points
      
  validation:
    - metric: "contamination_actual"
      bounds: [0.03, 0.08]  # Must be 3-8% (not 5% exactly)
    - metric: "precision_on_known_incidents"
      bounds: [0.90, 1.0]
    
  promotion: "canary -> 10% traffic -> 100%"
```

---

## Notification Throttling

### Problem

Driver gets 10 alerts/min if not throttled (jitter oscillates, ETA updates every 10s).

### Solution

```python
def should_notify_driver(van_id: str, notification_type: str, payload: dict) -> bool:
    """
    Throttle to max 2 notifications/van/hour.
    Priority: LIFE_CRITICAL > ALERT > UPDATE
    """
    
    # Redis key: throttle window (1 hour, rolling)
    key = f"notif:throttle:{van_id}"
    
    current_count = redis.get(key) or 0
    
    if current_count >= 2:
        # At quota, only allow LIFE_CRITICAL
        if notification_type == "LIFE_CRITICAL":
            # Override: remove oldest low-priority
            remove_lowest_priority_notif(van_id)
            redis.incr(key)
            return True
        return False
    
    redis.incr(key)
    redis.expire(key, 3600)  # TTL 1 hour
    return True

@async_task
def send_notification(driver_id, message, urgency):
    """
    Queue → APNs/FCM with exponential backoff.
    """
    for attempt in range(3):
        try:
            push_notification(driver_id, message, urgency)
            audit_log(driver_id, "notification_sent", message)
            return
        except Exception as e:
            wait = 2 ** attempt  # 1s, 2s, 4s
            sleep(wait)
    
    audit_log(driver_id, "notification_failed_all_retries", message)
```

---

## Cosmos DB Schema (Van State)

```javascript
{
  "id": "VAN-0042",  // Partition key
  "van_id": "VAN-0042",
  "driver_id": "DRV-1234",
  "status": "IN_TRANSIT",
  "location": {
    "lat": 19.0760,
    "lon": 72.8777,
    "timestamp_utc": 1711193400000  // Epoch ms
  },
  "route": {
    "route_id": "ROUTE-2026-03-22-001",
    "assigned_at_utc": 1711192800000,
    "waypoints": [
      { "sequence": 1, "lat": 19.0760, "lon": 72.8777, "eta_utc": 1711194600000 }
    ]
  },
  "sensor_state": {
    "safe_to_continue": true,
    "tyre_psi_min": 32.1,
    "anomaly_detected": false,
    "updated_at_utc": 1711193400000
  },
  "telemetry_freshness_sec": 5,
  "alerts": [
    { "alert_id": "...", "severity": "WARNING", "created_at_utc": ... }
  ],
  "_ts": 1711193400,  // Cosmos timestamp (seconds)
  "ttl": 2592000  // 30 days (archive to cold storage)
}
```

**Indexes:**
- Primary: `id` (van_id)
- Composite: `(status, updated_at_utc)` for bulk queries
- No spatial indexes (H3 partition key handles geo)

---

## Redis Cache Strategy

```
Key pattern: "<namespace>:<object_id>[:<sub_key>]"

1. Route Cache (5 min TTL)
   ├─ route:<van_id>:<route_id> → {waypoints, eta}
   └─ h3:<cell_id>:vans → set of van_ids (update every 5 sec)

2. Sensor Cache (10 sec TTL, higher update frequency)
   └─ sensor:<van_id> → {tyre_psi_min, safe_to_continue, ...}

3. Throttle Cache (3600 sec TTL)
   └─ notif:throttle:<van_id> → count (integer)

4. Lock Cache (distributed)
   └─ lock:reroute:<van_id> → TTL 30 sec (prevent concurrent reroutes)
```

---

**Document Version:** 1.0  
**Last Updated:** 2026-03-22
