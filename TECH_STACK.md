# Tech Stack & Infrastructure Reference

## Technology Selection Rationale

### Messaging & Stream Processing

| Component | Technology | Why This Choice |
|-----------|-----------|-----------------|
| **Message Broker** | Azure Event Hubs (Kafka API) | Supports 1M events/sec, native Azure integration, 7-day retention, no infra management |
| **Stream Processor** | Azure Stream Analytics | <2s latency for stateful operations (Kalman filter, anomaly), SQL-like DSL, cost-efficient |
| **Hot-Path Language** | Azure Stream Analytics (SQL-like) | Pre-compiled for performance, no JVM/Python startup overhead |

**Considered Alternatives:**
- Apache Kafka: Better ops control; rejected due to self-managed overhead for 99.95% SLA
- Spark Streaming: Micro-batch (>100ms latency); too slow for jitter detection
- Kafka Streams: Would require containerization; ASA simpler for this use case

### Routing & Optimization

| Component | Technology | Why This Choice |
|-----------|-----------|-----------------|
| **Routing Engine** | Google OR-Tools (C++) | Industry-standard VRP solver, <100ms latency, 7-day time windows |
| **Deployment** | AKS (Kubernetes) | Horizontal scaling, sidecar for cache preload, gRPC for 10ms latency |
| **Language** | Python + C++ bindings | OR-Tools native, NumPy vectorization for feature engineering |

**Considered Alternatives:**
- OSRM (OpenStreetMap): Limited time-window support; locked into street-level accuracy
- Mapbox Matrix API: Cloud-dependent, per-call cost, <50 vans max per call

### ML & AI

| Component | Technology | Why This Choice |
|-----------|-----------|-----------------|
| **ETA Model** | XGBoost (tabular) | Fast inference (<50ms), handles non-linear time-domain features, Shapley explainability |
| **Anomaly Detection** | Isolation Forest | Unsupervised (no labeling overhead), contamination parameter tunable per van type |
| **Life-Critical AI** | LangGraph + LangChain | Structured agent with tools (route search, ETA lookup), audit trail, token budgeting |
| **LLM** | GPT-4 Turbo (primary), GPT-3.5 (fallback) | High reasoning for life-critical decisions, 128K context, function calling |
| **Feature Store** | Delta Lake (Databricks) | ACID transactions, time-travel for historical features, ZOrder optimization |
| **ML Ops** | MLflow | Model registry, serving inference, A/B test staging (canary to 10% drivers) |

**Considered Alternatives:**
- Prophet: Time-series forecasting; too slow for real-time ETA (batch only)
- AutoML (H2O): Black-box; unfeasible for regulatory audit trails on life-critical
- Custom DNN: Hard to interpret failures, overkill for tabular features

### Data & Storage

| Component | Technology | Why This Choice |
|-----------|-----------|-----------------|
| **OLTP (Van State)** | Azure Cosmos DB | Global replication implicit (future expansion), TTL on old docs, partition key by van_id |
| **Cache Layer** | Redis | Sub-millisecond, cluster mode for HA, Lua scripting for atomic route cache updates |
| **Time-Series OLAP** | Azure Data Explorer (ADX) | Optimized for telemetry ingestion (KQL), 1M events/sec, fast aggregations for ML features |
| **ML Features** | Delta Lake (Delta Parquet) | ACID, Z-order curve indexing by H3 geohash, time-travel for point-in-time features |

**Considered Alternatives:**
- PostgreSQL: Bottleneck at >10K msgs/sec; rejected for stream ingestion
- ClickHouse: Fast but no ACID; risky for audit logs on life-critical
- DynamoDB: Vendor lock-in, cost unpredictable at 3K events/sec

### Containers & Orchestration

| Component | Technology | Why This Choice |
|-----------|-----------|-----------------|
| **Container Runtime** | Docker | Industry standard, 500× smaller than VMs, SHA digest reproducibility |
| **Orchestration** | Kubernetes (AKS) | Auto-scaling (CPU metric), rolling updates, helm charts for gitops, pod disruption budgets |
| **Networking** | Azure Virtual Network + NSG | Egress to Google Cloud (OR-Tools endpoint in GCP), zero firewall latency within VNet |
| **Service Mesh** | No service mesh (at <10 services) | Mutual TLS at API gateway level; service mesh overhead not justified yet |

**Considered Alternatives:**
- Docker Swarm: Single region only; no multi-region HA
- Lambda (Serverless): Cold start >3s; unacceptable for <30s route update SLA
- App Service: No sidecar pattern (cache preload); not viable

### Observability & DevOps

| Component | Technology | Why This Choice |
|-----------|-----------|-----------------|
| **Logging** | Azure Application Insights + Log Analytics | Deep .NET integration, correlation IDs across services, KQL queries |
| **Metrics** | Prometheus (scraped by Azure Monitor) | Open standard, 15s scrape intervals sufficient, long-term storage in Azure |
| **Tracing** | OpenTelemetry → Application Insights | W3C trace context propagation; future-proofing against vendor change |
| **Alerting** | Azure Monitor + PagerDuty | Routing rules by severity, responder rotation, post-mortem automation |
| **IaC** | Terraform | Reproducible infrastructure, git history, drift detection, state locking in Azure Storage |

**Considered Alternatives:**
- ELK Stack: Self-managed burden at 5K vans; cost → $80K/month
- DataDog: Excellent but proprietary; metrics locked into UI
- Grafana: Best visualization; still requires Prometheus upstream

## Environment Variables & Secrets

### Mandatory (per environment)

```bash
# Event Hub
EVENTHUB_NAMESPACE=logistics-prod-eh.servicebus.windows.net
EVENTHUB_CONNECTION_STRING=<azure-provided>  # Stored in Key Vault

# Cosmos DB
COSMOS_ENDPOINT=https://logistics-prod.documents.azure.com:443/
COSMOS_KEY=<azure-keyvault>

# Redis
REDIS_HOST=logistics-prod.redis.cache.azure.com
REDIS_PORT=6379
REDIS_PASSWORD=<keyvault>

# OR-Tools Service
OR_TOOLS_ENDPOINT=http://or-tools-service.default.svc.cluster.local:8080
OR_TOOLS_TIMEOUT_MS=20000

# LLM
OPENAI_API_KEY=<keyvault>
OPENAI_MODEL=gpt-4-turbo-preview

# Database
ADX_ENDPOINT=https://logisticsadx.northeurope.kusto.windows.net
ADX_DATABASE=telemetry
ADX_AUTH_TOKEN=<keyvault>
```

### Optional (sensible defaults)

```bash
JITTER_THRESHOLD_M=40.0                # GPS accuracy
KALMAN_PROCESS_NOISE=1e-7
ISOLATION_FOREST_CONTAMINATION=0.05
STREAM_ANALYTICS_BACKLOG_THRESHOLD_SEC=10
NOTIFICATION_THROTTLE_PER_VAN_PER_HOUR=2
```

## Version Compatibility Matrix

| Component | Version | Min | Max | Notes |
|-----------|---------|-----|-----|-------|
| Python | 3.11 | 3.9 | 3.12 | NumPy 2.0 compatible |
| XGBoost | 2.0.3 | 1.7 | — | Quantile loss objective |
| scikit-learn | 1.3.x | 1.1 | — | IsolationForest API stable |
| Kubernetes | 1.28 | 1.27 | 1.29 | CRD: EndpointSlice |
| OR-Tools | 9.7.x | 9.6 | — | gRPC breaking change in 9.8 |
| Azure SDK | 1.13.x | 1.10 | — | CosmosDB bulk import |

## Cost Breakdown (Monthly, ~5K vans, Mumbai region)

| Service | Unit | Qty | Cost USD | Notes |
|---------|------|-----|---------|-------|
| **Event Hubs** | Throughput unit | 12 | 1,920 | 12 Mbps sustained |
| **Stream Analytics** | KU (Kinetic Unit) | 6 | 960 | 3×2KU for HA |
| **AKS** | vCPU | 12 | 2,400 | 3×4 (routing + AI) |
| **Cosmos DB** | RU/sec + storage | 5K RU + 100GB | 2,500 | Range ops for routing |
| **Redis** | Standard tier | 1×6GB | 850 | Cache layer |
| **Data Explorer** | 2 compute + storage | 2 + 500GB | 1,200 | Telemetry OLAP |
| **Application Insights** | Data ingestion | 50GB/month | 250 | Logs + traces |
| **Key Vault** | Secrets + ops | 50K ops | 50 | Secrets rotation |
| **Storage Account** | Blobs (cold tier) | 5TB archive | 30 | Event Hub capture |
| **Databricks** | All-purpose cluster | 20 DBU/day | 800 | ML retraining |
| **OpenAI API** | Tokens (gpt-4-turbo) | 500K tokens/day | 3,000 | Life-critical decisions |
| **Bandwidth** | Egress to GCP | 10TB/month | 900 | OR-Tools API calls |
| **Monitoring** | Azure Monitor + PagerDuty | — | 500 | Alerting + runbooks |
| | | **TOTAL** | **$15,460/month** | **~$3.10/van** |

## Scaling Targets

- **GPS Throughput:** Currently 5 vans/sec × 32 partitions = 160 msgs/sec (scale to 10K+ vans by +8 KUs)
- **Route Computation:** 100ms per van × 5K vans = 500s batch (async scheduling, amortize)
- **ML Retraining:** 7-day historical data (30B telemetry points, 4 GPU hours on Databricks)

---

**Document Version:** 1.0  
**Last Updated:** 2026-03-22
