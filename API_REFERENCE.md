# API Reference & Data Models

## Base URL

**Production:** `https://api.logistics.mayank1407.in/v1`  
**Staging:** `https://staging-api.logistics.mayank1407.in/v1`  
**Local:** `http://localhost:8080/v1`

## Authentication

All requests require:
```
Authorization: Bearer <JWT_TOKEN>
X-API-Key: <API_KEY>  # Legacy, being phased out
Content-Type: application/json
```

**JWT Structure:**
```json
{
  "sub": "driver_id",
  "role": "driver|dispatcher|admin",
  "van_id": "VAN-0042",
  "exp": 1711192800,
  "iat": 1711106400
}
```

---

## Endpoints

### 1. **GET /routes/{van_id}/current**

Fetch current assigned route for a van.

**Request:**
```bash
curl -X GET https://api.logistics.mayank1407.in/v1/routes/VAN-0042/current \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json"
```

**Response (200 OK):**
```json
{
  "van_id": "VAN-0042",
  "route_id": "ROUTE-2026-03-22-001",
  "status": "ACTIVE",
  "waypoints": [
    {
      "sequence": 1,
      "lat": 19.0760,
      "lon": 72.8777,
      "location_name": "Lab A (pickup)",
      "arrival_window": {
        "earliest_utc": "2026-03-22T14:00:00Z",
        "latest_utc": "2026-03-22T14:15:00Z"
      },
      "stop_duration_sec": 180,
      "cargo": {
        "package_ids": ["PKG-1001", "PKG-1003"],
        "priority_class": "LIFE_CRITICAL",
        "weight_kg": 2.5
      }
    },
    {
      "sequence": 2,
      "lat": 19.0156,
      "lon": 72.8295,
      "location_name": "Hospital Central (dropoff)",
      "delivery_sla_utc": "2026-03-22T15:30:00Z",
      "stop_duration_sec": 300
    }
  ],
  "eta_minutes": 32,
  "distance_km": 14.2,
  "route_computed_at_utc": "2026-03-22T13:58:00Z",
  "route_expires_at_utc": "2026-03-22T14:20:00Z",
  "optimization_algorithm": "or-tools-vrp",
  "traffic_congestion_level": "HIGH",
  "driver_notification_id": "NOTIF-2026-03-22-042-001"
}
```

**Error (404):**
```json
{
  "error": "van_not_found",
  "message": "VAN-0042 not found in active fleet",
  "status": 404
}
```

---

### 2. **POST /routes/{van_id}/request-reroute**

Request emergency reroute (e.g., vehicle breakdown, traffic jam).

**Request:**
```json
{
  "reason": "breakdown|traffic|medical_priority|other",
  "current_location": {
    "lat": 19.0760,
    "lon": 72.8777,
    "accuracy_m": 5.2
  },
  "urgency": "normal|high|critical",
  "package_ids_to_drop": ["PKG-1001"],  # Optional
  "notes": "Engine overheating, need coolant stop"
}
```

**Response (202 ACCEPTED):**
```json
{
  "request_id": "REROUTE-2026-03-22-001",
  "status": "PROCESSING",
  "estimated_decision_time_sec": 12,
  "current_route_cancelled": false,
  "message": "Rerouting in progress. You'll receive update via push notification."
}
```

**Failure (400):**
```json
{
  "error": "invalid_package_id",
  "message": "PKG-1001 not on current route",
  "status": 400,
  "suggestion": "Available packages: PKG-1003, PKG-1004"
}
```

---

### 3. **GET /vans/{van_id}/telemetry/latest**

Get latest sensor + GPS telemetry for a van.

**Request:**
```bash
curl -X GET https://api.logistics.mayank1407.in/v1/vans/VAN-0042/telemetry/latest \
  -H "Authorization: Bearer <token>"
```

**Response (200 OK):**
```json
{
  "van_id": "VAN-0042",
  "timestamp_utc": "2026-03-22T14:12:30.500Z",
  "gps": {
    "lat": 19.0760122,
    "lon": 72.8777456,
    "speed_kmh": 18.5,
    "heading_deg": 245,
    "accuracy_m": 4.2,
    "geo_hash": "ttfxq",
    "jitter_status": "NORMAL"  # NORMAL | JITTER | UNKNOWN
  },
  "sensors": {
    "tyre_psi_min": 32.1,
    "engine_temp_c": 88.2,
    "fuel_level_pct": 45.0,
    "health_score": 0.94,
    "alert_flags": 0,  # Bitmask: bit0=low_fuel, bit1=overtemp, etc.
    "safe_to_continue": true,
    "anomaly_detected": false
  },
  "route_status": {
    "current_waypoint_sequence": 1,
    "eta_to_next_stop_min": 8,
    "time_to_sla_sec": 1050,  # Seconds remaining before SLA breach
    "sla_status": "ON_TRACK"  # ON_TRACK | AT_RISK | BREACHED
  }
}
```

---

### 4. **POST /decisions/life-critical**

Submit a life-critical delivery for AI approval (internal endpoint, dispatcher use).

**Request:**
```json
{
  "manifest_id": "MANIFEST-2026-03-22-001",
  "van_id": "VAN-0042",
  "priority_class": "LIFE_CRITICAL",
  "cargo": {
    "description": "3× blood units O-, 4h expiry",
    "weight_kg": 2.5,
    "hazmat_class": null
  },
  "delivery_sla_utc": "2026-03-22T15:30:00Z",
  "current_location": {
    "lat": 19.0760,
    "lon": 72.8777
  },
  "destination_zone": "hospital_central"
}
```

**Response (202 ACCEPTED):**
```json
{
  "decision_id": "DECISION-2026-03-22-042-001",
  "status": "PENDING",
  "estimated_decision_time_sec": 8,
  "webhook_url": "/webhooks/decisions/DECISION-2026-03-22-042-001"
}
```

**Poll Decision Status:**
```bash
curl -X GET https://api.logistics.mayank1407.in/v1/decisions/DECISION-2026-03-22-042-001 \
  -H "Authorization: Bearer <token>"
```

**Webhook Callback (once complete):**
```json
POST /YOUR_WEBHOOK_URL
{
  "decision_id": "DECISION-2026-03-22-042-001",
  "status": "APPROVED|HELD|REROUTED",
  "decision": {
    "approval": "APPROVED",
    "route_waypoints": [...],
    "eta_minutes": 32,
    "reasoning": "ETA 32 min << SLA 1800 sec; sensor state healthy",
    "confidence_score": 0.96,
    "alternative_considered": ["reroute_via_eastbound"],
    "timestamp_utc": "2026-03-22T14:12:45.123Z"
  }
}
```

---

### 5. **GET /analytics/fleet-status**

Dashboard endpoint: current fleet health snapshot.

**Request:**
```bash
curl -X GET "https://api.logistics.mayank1407.in/v1/analytics/fleet-status?time_window_min=60" \
  -H "Authorization: Bearer <token>"
```

**Response (200 OK):**
```json
{
  "timestamp_utc": "2026-03-22T14:15:00Z",
  "fleet_summary": {
    "total_vans": 5000,
    "active_vans": 4987,
    "idle_vans": 13,
    "vans_in_maintenance": 5,
    "vans_with_alerts": 23
  },
  "alert_breakdown": {
    "sensor_anomalies": 8,
    "gps_jitter_detected": 5,
    "sla_at_risk": 7,
    "critical_incidents": 3
  },
  "efficiency_metrics": {
    "avg_route_utilization_pct": 87.3,
    "on_time_delivery_pct": 96.2,
    "avg_delivery_time_min": 28.1
  },
  "critical_incidents": [
    {
      "van_id": "VAN-0103",
      "incident_type": "TIRE_LEAK",
      "detected_at_utc": "2026-03-22T14:10:00Z",
      "status": "DISPATCHER_NOTIFIED",
      "recommended_action": "Divert to nearest repair facility"
    }
  ]
}
```

---

## Data Models

### Van State Model

```json
{
  "van_id": "VAN-0042",
  "driver_id": "DRV-1234",
  "status": "ACTIVE|IDLE|MAINTENANCE|OFFLINE",
  "current_location": {
    "lat": 19.0760122,
    "lon": 72.8777456,
    "updated_at_utc": "2026-03-22T14:12:30.500Z"
  },
  "current_route_id": "ROUTE-2026-03-22-001",
  "fuel_level_pct": 45.0,
  "cargo_weight_kg": 12.5,
  "cargo_utilization_pct": 62.5,
  "fleet_id": "MUMBAI-SOUTH",
  "firmware_version": "3.2.1",
  "vehicle_type": "VEHICLE_TYPE_DCDOOR_LARGE",
  "registration_date": "2024-01-15",
  "last_service_date": "2026-03-10",
  "telemetry_freshness_sec": 5
}
```

### Manifest Model

```json
{
  "manifest_id": "MANIFEST-2026-03-22-001",
  "van_id": "VAN-0042",
  "created_at_utc": "2026-03-22T13:45:00Z",
  "packages": [
    {
      "package_id": "PKG-1001",
      "weight_kg": 1.2,
      "dimensions_cm": {"length": 20, "width": 15, "height": 10},
      "priority_class": "LIFE_CRITICAL",
      "pickup_location": {"lat": 19.0760, "lon": 72.8777, "name": "Lab A"},
      "delivery_location": {"lat": 19.0156, "lon": 72.8295, "name": "Hospital Central"},
      "delivery_sla_utc": "2026-03-22T15:30:00Z",
      "recipient_phone": "+91-*****1234",
      "special_instructions": "Keep cold (4°C)"
    }
  ],
  "manifest_status": "LOADED|IN_TRANSIT|PARTIAL_UNLOADED|COMPLETED",
  "total_weight_kg": 12.5,
  "completion_reason": null  # Set when manifest_status = COMPLETED
}
```

### Alert Model

```json
{
  "alert_id": "ALERT-2026-03-22-042-001",
  "van_id": "VAN-0042",
  "alert_type": "SENSOR_ANOMALY|GPS_JITTER|SLA_AT_RISK|FUEL_LOW|TIRE_PRESSURE|TEMP_HIGH|CRITICAL_INCIDENT",
  "severity": "INFO|WARNING|CRITICAL",
  "triggered_at_utc": "2026-03-22T14:10:00Z",
  "resolved_at_utc": null,
  "message": "Tyre PSI minimum dropped to 28.5 PSI (threshold: 30 PSI)",
  "telemetry_snapshot": {
    "tyre_psi_min": 28.5,
    "engine_temp_c": 87.2,
    "fuel_level_pct": 45.0
  },
  "recommended_actions": [
    "Divert to nearest tire repair facility",
    "Check for slow leak or puncture"
  ],
  "dispatcher_acked": false,
  "driver_acked": false
}
```

---

## Error Responses

All errors follow RFC 7807 (Problem Details):

```json
{
  "type": "https://api.logistics.mayank1407.in/errors/invalid-manifest",
  "title": "Invalid Manifest ID",
  "status": 400,
  "detail": "Manifest MANIFEST-99999 does not exist",
  "instance": "/v1/decisions/life-critical",
  "trace_id": "0HN41EE91AOQP:00000001",
  "timestamp_utc": "2026-03-22T14:12:45Z"
}
```

**Common Status Codes:**
- `200 OK` — Successful GET
- `201 Created` — Resource created
- `202 Accepted` — Async job submitted
- `400 Bad Request` — Invalid input
- `401 Unauthorized` — Missing/invalid auth
- `403 Forbidden` — Insufficient permissions
- `404 Not Found` — Resource not found
- `409 Conflict` — Request conflicts with current state
- `429 Too Many Requests` — Rate limit exceeded
- `500 Internal Server Error` — Server error (with trace_id)

---

## Rate Limiting

**Headers returned on all responses:**
```
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 997
X-RateLimit-Reset: 1711192800
```

**Limits:**
- **Global:** 10,000 req/min per API key
- **Per-van:** 100 req/min per van_id
- **Life-critical endpoint:** 50 req/min per dispatcher

---

## Webhooks

For async decision callbacks, configure webhook URL in your account settings:

```bash
# POST to your webhook
{
  "event_type": "decision.completed",
  "decision_id": "DECISION-...",
  "timestamp_utc": "2026-03-22T14:12:45.123Z",
  "data": {...}
}

# Signature verification (HMAC-SHA256)
X-Signature-256: sha256=<base64(hmac)>
```

**Retry Policy:**
- 3 retries with exponential backoff (2s, 4s, 8s)
- Timeout: 30 seconds

---

## SDK Examples

### Python

```python
from logistics_api import LogisticsClient

client = LogisticsClient(
    api_key="sk_live_...",
    base_url="https://api.logistics.mayank1407.in/v1"
)

# Get current route
route = client.routes.get_current(van_id="VAN-0042")
print(f"ETA: {route.eta_minutes} min")

# Request reroute
decision = client.routes.request_reroute(
    van_id="VAN-0042",
    reason="breakdown",
    urgency="high"
)
print(f"Reroute ID: {decision.request_id}")
```

### JavaScript

```javascript
import { LogisticsClient } from '@mayank1407/logistics-api';

const client = new LogisticsClient({
  apiKey: 'sk_live_...',
  baseURL: 'https://api.logistics.mayank1407.in/v1'
});

// Fetch fleet status
const fleetStatus = await client.analytics.getFleetStatus({
  time_window_min: 60
});

console.log(`Active vans: ${fleetStatus.fleet_summary.active_vans}`);
```

---

**Document Version:** 1.0  
**Last Updated:** 2026-03-22  
**OpenAPI Spec:** [Available at `/openapi.json`](https://api.logistics.mayank1407.in/openapi.json)
