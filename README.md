# Predictive Logistics Engine
### Real-time intelligent fleet management — Mumbai simulation

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/YOUR_USERNAME/predictive-logistics-engine/blob/main/notebooks/01_data_generation_and_schema.ipynb)

A proof-of-concept simulation of the **Predictive Logistics Engine** — an AI-driven system that replaces static delivery routes with real-time, context-aware routing decisions for a fleet of 5,000 vans across Mumbai.

**What makes it intelligent:**
- 🚨 **LangGraph AI agents** reason about life-critical decisions (blood, organs, vaccines)
- ⚡ **Hot path** (<2s): Kalman filter + Isolation Forest detect anomalies in real-time
- 🔥 **Warm path** (<30s): OR-Tools + LangGraph AI optimize routes with Friday variance detection
- ❄️ **Cold path** (batch): XGBoost + Isolation Forest models retrain daily on historical data

This repository demonstrates the algorithms, data schemas, and business results described in the system design. All simulations use real Mumbai geography (BKC, Dharavi, Andheri, Lower Parel corridors).

---

## What this proves

| Interview Task | Notebook | What it shows |
|---|---|---|
| Task 1 — 99% OTD + fuel reduction | Notebook 3 | Dynamic vs static OTD by hour, 15% fuel saving |
| Task 2 — Friday variance +400% | Notebooks 2 + 3 | Std-dev spike at 14:00, cost function switch |
| Task 3 — Van #402 tyre + LIFE_CRITICAL | Notebooks 2 + 3 | Isolation Forest anomaly, 30-sec decision timeline |
| Task 4a — Telemetry schema at scale | Notebook 1 | Schema validation, 117k rows, Avro contracts |
| Task 6 — GPS jitter vs traffic stall | Notebook 2 | Kalman filter + 3-signal ensemble |

---

## Repository structure

```
predictive-logistics-engine/
│
├── README.md                              ← This file
├── AGENTS.md                              ← AI agent context for Copilot/Claude
│
├── 📚 DOCUMENTATION (new!)
│   ├── FLOWS.md                           ← **Start here** End-to-end message flows
│   ├── ARCHITECTURE.md                    ← Layered system architecture + data flow
│   ├── TECH_STACK.md                      ← Technology rationale + cost breakdown
│   ├── PROMPTS.md                         ← LLM prompts for AI agents
│   ├── SYSTEM_DESIGN.md                   ← Decision trees, state machines, patterns
│   ├── DEVELOPMENT.md                     ← Setup guide + contribution workflow
│   └── API_REFERENCE.md                   ← REST API docs + data models
│
├── notebooks/
│   ├── 01_data_generation_and_schema.ipynb   ← Generate data + validate schemas
│   ├── 02_intelligence_algorithms.ipynb      ← Kalman, Isolation Forest, XGBoost, H3
│   └── 03_business_results_and_insights.ipynb ← OTD, fuel, Friday variance, Van #402
│
├── data/
│   ├── simulate.py                        ← Standalone data generator script
│   └── sample/
│       ├── gps_telemetry.csv              ← 117,600 GPS events (100 vans, 7 days)
│       ├── sensor_telemetry.csv           ← 117,600 sensor events
│       └── package_manifest.csv           ← 5,600 package events
│
├── schemas/
│   ├── gps_telemetry.avsc                 ← Avro schema — GPS stream
│   ├── sensor_telemetry.avsc              ← Avro schema — Sensor stream
│   └── package_manifest.avsc              ← Avro schema — Manifest stream
│
└── docs/
    └── architecture.md                    ← Full system architecture (legacy)
```

---

## 📖 Documentation Quick Links

| Document | Purpose | Key Topics |
|----------|---------|-----------|
| **[FLOWS.md](FLOWS.md)** | **Start here!** End-to-end message flows | Rerouting logic, notification flow, schema columns, conditionals |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | System design & data flows | Layers, Event Hub topics, hot/warm/cold paths |
| **[TECH_STACK.md](TECH_STACK.md)** | Tech selection & ops | Azure services, cost $15K/mo, scaling |
| **[PROMPTS.md](PROMPTS.md)** | AI agent reasoning | Life-critical prompts, few-shot examples, versioning |
| **[SYSTEM_DESIGN.md](SYSTEM_DESIGN.md)** | Deep technical patterns | H3 partitioning, state machines, decision trees |
| **[DEVELOPMENT.md](DEVELOPMENT.md)** | Getting started | Local setup, testing, code standards, git workflow |
| **[API_REFERENCE.md](API_REFERENCE.md)** | REST API & SDKs | Endpoints, models, rate limits, webhooks |
| **[AGENTS.md](AGENTS.md)** | AI context for coding assistants | Problem statement, conventions, anti-patterns |

---

## Quick start — Google Colab

Run all three notebooks in sequence. Each takes **under 5 minutes** on a free Colab runtime.

**Step 1:** Open Notebook 1 and run all cells — generates the simulated data
**Step 2:** Open Notebook 2 — runs Kalman filter, Isolation Forest, XGBoost
**Step 3:** Open Notebook 3 — produces all business results charts

Click the Colab badge above or open notebooks directly:

- [Notebook 1 — Data Generation & Schema Validation](notebooks/01_data_generation_and_schema.ipynb)
- [Notebook 2 — Intelligence Algorithms](notebooks/02_intelligence_algorithms.ipynb)
- [Notebook 3 — Business Results & Insights](notebooks/03_business_results_and_insights.ipynb)

---

## Simulation parameters

| Parameter | Simulation | Production |
|---|---|---|
| Fleet size | 100 vans | 5,000 vans |
| Telemetry cadence | 5 minutes | 5 seconds |
| Duration | 7 days | Continuous |
| GPS jitter vans | 10% | 10% (per problem statement) |
| Incident van | VAN-0042 (Day 3, 14:30) | Dynamic |
| City | Mumbai (real coordinates) | Mumbai |

> The algorithms and schemas scale linearly. Production throughput: 3,000+ events/sec via Azure Event Hubs (20 TU, auto-inflate to 40).

---

## Three Processing Paths: Real-time Intelligence

```
             GPS/Sensor Events
                    │
        ┌───────────┼───────────┐
        │           │           │
        ▼           ▼           ▼
    HOT PATH    WARM PATH    COLD PATH
   (<2 sec)    (<30 sec)    (Batch)
        │           │           │
   ┌────┴────┐      │      ┌────┴────┐
   │ Kalman  │      │      │XGBoost  │
   │ Filter  │      │      │Retrain  │
   │+ Anomaly│      │      │+ Feature│
   │Detection│      │      │Engineer │
   └────┬────┘      │      └────┬────┘
        │           │           │
   Cache alerts  LangGraph   Update models
   to Redis      AI Agent    (MLflow)
                    │
                 Route decision
                    ↓
            Driver notification
               (< 30 sec total)
```

### Three Paths Explained

| Path | Latency | Technology | What It Does | Example |
|------|---------|-----------|--------------|---------|
| **🔥 Hot** | <2s | Azure Stream Analytics | Real-time anomaly detection + GPS smoothing | Sensor spike detected, flag driver immediately |
| **⚡ Warm** | <30s | AKS + LangGraph + OR-Tools | AI-driven route optimization + decision reasoning | Life-critical manifest arrives → AI agent approves route in <15s |
| **❄️ Cold** | Daily | Databricks + MLflow | ML model retraining + feature engineering | Retrain XGBoost ETA model on 7-day window Friday 3 AM |

---

## Algorithms & AI Agents Implemented

| Component | Technology | Purpose | Notebook |
|-----------|-----------|---------|----------|
| **🤖 LangGraph Agent** | LangChain + LangGraph | Life-critical delivery decisions (APPROVED/HELD/REROUTED) | [PROMPTS.md](PROMPTS.md) + production system |
| **Kalman Filter** | NumPy | GPS jitter detection — Signal 1 of 3-signal ensemble | Notebook 2 |
| **Isolation Forest** | scikit-learn | Sensor anomaly detection — Van #402 PSI drop | Notebook 2 |
| **XGBoost** | XGBoost | ETA prediction + Friday regime detection | Notebook 2 |
| **3-Signal Ensemble** | Custom | Final jitter vs traffic stall classification | Notebook 2 |
| **CVRPTW** (conceptual) | Google OR-Tools | Route optimization (speed vs variance) | Notebook 3 |
| **H3 Geospatial Index** | H3 | Peer-van corroboration lookup (O(1) no joins) | Notebooks 1+2 |

---

## AI Agent: LangGraph-Powered Life-Critical Decisions

### What the AI Agent Does

For **life-critical shipments** (blood, organs, vaccines), the system doesn't use static routing rules—it deploys a **LangGraph multi-agent AI** to reason about:

- **Safety**: Can this van physically deliver? (sensor checks, fuel, distance reachable?)
- **Time**: Will we make the SLA? (ETA model + traffic jam detection?)
- **Alternatives**: If primary route fails, what's the fallback? (reroute, hub pickup?)
- **Accountability**: Why did we make this decision? (audit trail, confidence score, reasoning chain)

### Decision Timeline: 30 Seconds Total

```
T=0s    Vehicle assigns LIFE_CRITICAL manifest
        └─ PackageManifest event → Event Hub

T<2s    Stream Analytics validates cargo properties
        ├─ Check: safe_to_continue flag (sensor anomaly gate)
        ├─ Check: tyre_psi_min > 28 PSI
        └─ Check: fuel_level > 15%

T<5s    LangGraph Agent Invoked
        ├─ Tool 1: Route Searcher
        │   └─ Search OR-Tools graph for feasible paths
        ├─ Tool 2: ETA Predictor  
        │   └─ XGBoost inference on candidate routes
        ├─ Tool 3: Anomaly Context Lookup
        │   └─ Query Cosmos DB for historical incidents
        └─ Tool 4: Traffic Regime Detector
            └─ Friday PM check (variance-minimization mode)

T<15s   Agent Decision Logic (Chain-of-Thought)
        ├─ IF sensor anomaly THEN → HOLD (no exceptions)
        ├─ IF time_to_sla < 5 min THEN → flag for review
        ├─ IF ETA > SLA THEN → consider reroute alternatives  
        └─ ELSE → APPROVED with confidence score

T<20s   Output: Decision JSON
        {
          "status": "APPROVED|HELD|REROUTED",
          "routes_considered": [...],
          "chosen_route": {...},
          "eta_minutes": 32,
          "confidence_score": 0.96,
          "reasoning": "..."
        }

T<30s   Driver Notification
        └─ Notification Hub → APNs/FCM → Driver app
```

### LangGraph Agent Architecture

```python
# State Machine (simplified pseudocode)
class LifeCriticalAgent(LangGraph.Agent):
    
    state = {
        "manifest_id": str,
        "van_id": str,
        "cargo_description": str,
        "delivery_sla_utc": datetime,
        "routes_evaluated": [],
        "decision": str,  # APPROVED | HELD | REROUTED
        "confidence": float
    }
    
    # Tools the agent can call
    tools = [
        route_search(van_id, destination) → List[Route],
        eta_predict(route, time_of_day, dow) → {eta_min, p90_eta_min},
        anomaly_lookup(van_id) → {incidents, alerts, risk_score},
        traffic_regime_detect(zone_h3, hour) → "normal" | "high_variance"
    ]
    
    # Decision flow
    def process(manifest):
        1. Check van safety (sensor gate)
        2. Search 3-5 route alternatives
        3. Predict ETA for each route → compare to SLA
        4. Apply Friday variance logic (if applicable)
        5. Reason about risk/confidence
        6. Output decision + alternatives
```

### What Happens in Each Decision Scenario

**Scenario 1: APPROVED** (Confidence 0.96)
```
Input:  Blood units (4h expiry), SLA 30 min, sensor OK
Output: APPROVED
        Route: south_ring (12 km, ETA 28 min)
        Confidence: 0.96
        Reason: "ETA 28 min << SLA 30 min buffer; sensor state healthy"
        Alternative: "Inland route (4 min slower, but safer on Friday PM)"
```

**Scenario 2: HELD** (Confidence 0.92)
```
Input:  Ventilator cartridges, SLA 8 min (!), Friday 5 PM peak, sensor OK
Output: HELD
        Reason: "SLA margin too tight (8 min) + Friday PM peak traffic"
        Hold Alternative: "Request hub night pickup (defer 4h, guaranteed delivery by 23:00)"
        Next Steps: "Dispatcher override required for same-day delivery"
```

**Scenario 3: REROUTED** (Confidence 0.88)
```
Input:  Organ transplant, SLA 45 min, primary facility closed
Output: REROUTED
        Original Route: Hospital A (30 km, now inaccessible)
        New Route: Hospital B (32 km, 32 min ETA, emergency dept receptive)
        Reason: "Primary site unavailable; backup facility confirmed ready"
        Confidence: 0.88 (backup logistics adds uncertainty)
```

### AI Agent Audit Trail (LangSmith Integration)

Every decision is logged in **LangSmith** with:

```json
{
  "decision_id": "DECISION-2026-03-22-042-001",
  "timestamp_utc": "2026-03-22T14:12:45.123Z",
  "manifest_id": "MANIFEST-2026-03-22-001",
  "van_id": "VAN-0042",
  
  "reasoning_chain": [
    "Step 1: Checked sensor safety gate → safe_to_continue = true ✓",
    "Step 2: Evaluated 3 routes (south_ring, inland, eastbound)",
    "Step 3: Predicted ETA south_ring = 28 min (p90 = 32 min)",
    "Step 4: Compared vs SLA = 30 min → buffer = 2 min ✓",
    "Step 5: Friday 2 PM detected (variance regime), but buffer sufficient",
    "Step 6: Driver rating historical (4.9/5), no recent incidents",
    "Decision: APPROVED (confidence 0.96)"
  ],
  
  "tools_invoked": [
    {"tool": "route_search", "time_ms": 120, "result": "3 routes found"},
    {"tool": "eta_predict", "time_ms": 45, "result": "ETA 28 min"},
    {"tool": "anomaly_lookup", "time_ms": 80, "result": "No flagged incidents"},
    {"tool": "traffic_regime", "time_ms": 30, "result": "friday_pm_high_variance"}
  ],
  
  "total_decision_time_ms": 275,
  "fallback_used": false,
  "outcome": "DELIVERY_SUCCESSFUL",  # Set post-delivery
  "actual_delivery_time_min": 31
}
```

---

## Production architecture

In production, these streams flow through:

```
Van ECU / GPS unit
    → Azure IoT Hub (MQTT/AMQP)
    → Azure API Management (auth, rate limit)
    → Schema Registry (Avro validation)
    → Azure Event Hubs (3 topics, 32/16/8 partitions)
    → Stream Analytics (hot path, <2s)  +  AKS OR-Tools (warm path, <30s)  +  Databricks DLT (cold path)
    → LangGraph multi-agent (life-critical decisions)
    → Azure Notification Hubs → Driver mobile app (React Native)
```

Full architecture documentation: [docs/architecture.md](docs/architecture.md)

---

## Key design decisions

**H3 geo-hash as GPS partition key** — Spatial locality means vans in the same area land on the same partition, enabling peer-corroboration GPS jitter detection without cross-partition joins.

**tyre_psi_min pre-computed** — Stream Analytics reads one float field, not an array scan, at 1,000 events/sec. Small schema decision, large throughput impact.

**Friday cost function switch** — At 400% variance, the OR-Tools solver switches from minimise-ETA to minimise-90th-percentile-ETA. Choosing the most predictable route, not the fastest.

**LangGraph for Van #402** — A rule engine cannot compare two timelines (blowout risk window vs SLA window) dynamically, do external Redis lookups mid-decision, and produce an auditable LangSmith trace. LangGraph does all three.

---

## Requirements

```bash
pip install pandas numpy matplotlib seaborn scikit-learn xgboost scipy folium
```

No Azure services required to run the notebooks — everything runs locally or on Colab.

---

## License

MIT — feel free to use this simulation as a reference implementation.
