# Predictive Logistics Engine
### Real-time intelligent fleet management — Mumbai simulation

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/YOUR_USERNAME/predictive-logistics-engine/blob/main/notebooks/01_data_generation_and_schema.ipynb)

A proof-of-concept simulation of the **Predictive Logistics Engine** — an AI-driven system that replaces static delivery routes with real-time, context-aware routing decisions for a fleet of 5,000 vans across Mumbai.

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
    └── architecture.md                    ← Full system architecture documentation
```

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

## Algorithms implemented

| Algorithm | File | Purpose |
|---|---|---|
| **Kalman Filter** | Notebook 2 | GPS jitter detection — Signal 1 of 3-signal ensemble |
| **Isolation Forest** | Notebook 2 | Sensor anomaly detection — Van #402 PSI drop |
| **XGBoost** | Notebook 2 | ETA prediction + Friday regime detection |
| **3-Signal Ensemble** | Notebook 2 | Final jitter vs traffic stall classification |
| **CVRPTW** (conceptual) | Notebook 3 | OR-Tools routing objective — speed vs variance |
| **H3 Geospatial Index** | Notebooks 1+2 | Peer-van corroboration lookup |

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
