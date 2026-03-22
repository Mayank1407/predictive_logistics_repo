# Development Setup & Contribution Guide

## Quick Start (5 minutes)

### Prerequisites
- Python 3.11+
- Docker 24.0+
- PostgreSQL 14+ (for local testing)
- Azure CLI
- `git` & `gh` (GitHub CLI)

### 1. Clone & Setup Environment

```bash
git clone https://github.com/Mayank1407/predictive_logistics_repo.git
cd predictive_logistics_repo/logistics-engine

# Virtual environment
python -m venv venv
source venv/bin/activate  # macOS/Linux
# or
venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # Testing, linting, docs
```

### 2. Configure Secrets

Create `.env.local` in root:

```bash
# Event Hubs (local testing: Kafka mock)
KAFKA_BROKERS=127.0.0.1:9092
KAFKA_TOPIC_GPS=gps-telemetry
KAFKA_TOPIC_SENSOR=sensor-telemetry
KAFKA_TOPIC_MANIFEST=package-manifest

# Cosmos DB
COSMOS_ENDPOINT=https://localhost:8081/
COSMOS_KEY=C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QO/Sku93TkupbGq5ZoJ2nGeWZZMAkC7zVeDBEquJ90xJlcatQA==

# Redis
REDIS_HOST=127.0.0.1
REDIS_PORT=6379

# OpenAI (for AI agent, optional for local dev)
OPENAI_API_KEY=<your-key>  # Or skip local agent tests

# Databricks (for cold-path only, not needed for hotpath dev)
DATABRICKS_HOST=<your-workspace-url>
DATABRICKS_TOKEN=<your-token>
```

### 3. Start Local Infrastructure

```bash
docker-compose up -d

# Verify services are healthy
docker-compose ps
```

**This brings up:**
- Kafka (9092)
- Zookeeper (2181)
- Cosmos DB Emulator (8081)
- Redis (6379)
- PostgreSQL (5432)

### 4. Load Sample Data

```bash
python data/simulate.py \
  --vans 100 \
  --days 7 \
  --output data/sample/ \
  --seed 42
```

### 5. Run Tests

```bash
pytest tests/ -v --cov=src --cov-report=html
```

Open `htmlcov/index.html` to see coverage report.

---

## Development Workflow

### 1. Create a Feature Branch

```bash
git checkout -b feature/your-feature-name
# or for bug fixes:
git checkout -b fix/issue-number-description
```

**Branch naming convention:**
- `feature/kalman-filter-optimization`
- `fix/123-gps-jitter-false-positive`
- `docs/architecture-diagram`
- `chore/update-dependencies`

### 2. Make Changes & Test Locally

#### Type Hints (Mandatory)

```python
from typing import List, Dict, Optional, Tuple
import numpy as np

def kalman_smooth_positions(
    lats: np.ndarray,
    lons: np.ndarray,
    speeds: np.ndarray,
    accuracies: np.ndarray
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Apply Kalman filter to GPS positions.
    
    Args:
        lats: Latitude array (shape: n,)
        lons: Longitude array (shape: n,)
        speeds: Speed array in km/h (shape: n,)
        accuracies: GPS accuracy in meters (shape: n,)
    
    Returns:
        Tuple of (smoothed_lats, smoothed_lons, covariances)
    
    Raises:
        ValueError: If input arrays have mismatched lengths
    """
    if not (len(lats) == len(lons) == len(speeds) == len(accuracies)):
        raise ValueError("Input arrays must have matching length")
    
    # ... implementation
```

#### Constants (No Magic Numbers)

```python
# ❌ Bad
threshold = 40.0
std_threshold = 3

# ✅ Good
GPS_ACCURACY_THRESHOLD_M = 40.0  # Jitter threshold
ANOMALY_ZSCORE_THRESHOLD = 3.0  # Isolation Forest sigma
```

#### Testing Pattern

```python
import pytest
from src.algorithms import kalman_smooth_positions

class TestKalmanFilter:
    @pytest.fixture
    def sample_trajectory(self):
        """Clean GPS trajectory."""
        return {
            'lats': np.array([19.076, 19.077, 19.078]),
            'lons': np.array([72.877, 72.878, 72.879]),
            'speeds': np.array([20.0, 22.0, 21.0]),
            'accuracies': np.array([5.0, 4.5, 5.5])
        }
    
    def test_smoothing_reduces_variance(self, sample_trajectory):
        """Kalman should reduce variance on clean data."""
        slats, slons, cov = kalman_smooth_positions(**sample_trajectory)
        
        assert cov.mean() < 1e-6  # Low covariance on clean data
        assert len(slats) == 3
    
    def test_jitter_detection(self):
        """High-variance input should trigger jitter alert."""
        noisy = {
            'lats': np.array([19.076, 19.050, 19.077]),  # 2.7km jump
            'lons': np.array([72.877, 72.801, 72.879]),
            'speeds': np.zeros(3),  # Stationary
            'accuracies': np.array([50.0, 50.0, 50.0])  # Poor accuracy
        }
        slats, slons, cov = kalman_smooth_positions(**noisy)
        
        assert cov[1] > np.percentile(cov, 75)  # Spike detected
```

### 3. Run Pre-commit Checks

```bash
# Lint
pylint src/ tests/ --disable=invalid-name,too-many-arguments
black --check src/ tests/

# Format (auto-fix)
black src/ tests/
isort src/ tests/

# Type check (strict mode)
mypy src/ --strict
```

### 4. Commit with Conventional Commits

```bash
git add .
git commit -m "feat(kalman): add GPS covariance calculation

- Implement 2D Kalman filter for position smoothing
- Add configurable process noise (R, Q matrices)
- Performance: <100µs per position on CPU

Fixes #142
"
```

**Format:**
```
<type>(<component>): <subject>

<body (wrap at 72 chars)>

<footer (issue refs, breaking changes)>
```

**Types:** `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`

### 5. Push & Create Pull Request

```bash
git push origin feature/your-feature-name

# Open PR via GitHub CLI
gh pr create --title "Kalman Filter: covariance optimization" \
             --body "Reduces CPU overhead by 30%"
```

**PR Checklist:**
- [ ] Tests pass locally (`pytest`)
- [ ] Type hints added (`mypy`)
- [ ] Docstrings updated
- [ ] No hardcoded credentials
- [ ] Changelog entry added

### 6. Code Review & CI/CD

- **GitHub Actions will run:**
  - ✅ Unit tests
  - ✅ Linting (black, pylint)
  - ✅ Type checking (mypy)
  - ✅ Security scan (bandit)
  - ✅ Coverage report (must stay > 80%)

- **Merge when:** 
  - 1 approval from `@core-team`
  - All checks green
  - Branch up-to-date with `main`

---

## Project Structure

```
logistics-engine/
├── src/
│   ├── algorithms/
│   │   ├── kalman_filter.py
│   │   ├── isolation_forest.py
│   │   ├── xgboost_eta.py
│   │   └── __init__.py
│   ├── stream/
│   │   ├── gps_telemetry_processor.py
│   │   ├── sensor_anomaly_detector.py
│   │   └── manifest_router.py
│   ├── api/
│   │   ├── routes.py
│   │   ├── models.py
│   │   └── dependencies.py
│   ├── db/
│   │   ├── cosmos_client.py
│   │   ├── redis_cache.py
│   │   └── migrations/
│   └── __init__.py
├── tests/
│   ├── unit/
│   │   ├── test_kalman.py
│   │   ├── test_anomaly.py
│   │   └── test_eta_model.py
│   ├── integration/
│   │   ├── test_stream_pipeline.py
│   │   └── test_api_e2e.py
│   └── conftest.py
├── notebooks/
│   ├── 01_data_generation_and_schema.ipynb
│   ├── 02_intelligence_algorithms.ipynb
│   └── 03_business_results_and_insights.ipynb
├── docs/
│   ├── ARCHITECTURE.md
│   ├── TECH_STACK.md
│   ├── API_REFERENCE.md
│   └── DEVELOPMENT.md (this file)
├── scripts/
│   ├── setup_azure_infra.sh
│   ├── deploy_to_aks.sh
│   └── run_feature_engineering.py
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── .github/
│   └── workflows/
│       ├── tests.yml
│       ├── lint.yml
│       └── deploy.yml
└── README.md
```

---

## Running Notebooks

### Jupyter in VS Code

```bash
# Install Jupyter kernel
python -m ipykernel install --user --name logistics-env

# Open notebook
code notebooks/02_intelligence_algorithms.ipynb
```

### Or: Jupyter Server

```bash
jupyter notebook notebooks/
# Opens http://localhost:8888
```

**Important:** Always restart kernel before running. Data generations are seeded; rerun cells may give different results.

---

## Common Tasks

### Add New Algorithm

1. Create file: `src/algorithms/my_algorithm.py`
2. Add tests: `tests/unit/test_my_algorithm.py`
3. Update `src/algorithms/__init__.py` export
4. Add notebook demo: `notebooks/XX_...ipynb`
5. Document in `ALGORITHMS.md`

### Update Dependencies

```bash
# Edit requirements.txt, then:
pip install -r requirements.txt
pip freeze > requirements-lock.txt  # Lock to exact versions

git add requirements*.txt
git commit -m "chore: update dependencies (minor)"
```

### Deploy to Azure (Staging)

```bash
# Requires Azure CLI auth
./scripts/deploy_to_aks.sh --environment staging --image-tag v0.5.2

# Verify rollout
kubectl rollout status deployment/predictive-logistics -n staging
```

### Generate Docs

```bash
# Sphinx documentation
cd docs
make html
# Opens docs/_build/html/index.html
```

---

## Troubleshooting

### Docker containers won't start

```bash
docker-compose down -v  # Remove volumes
docker-compose up -d --build
```

### Type checking fails

```bash
# Check specific file
mypy src/algorithms/kalman_filter.py --show-error-codes

# Ignore external library stubs
mypy src/ --ignore-missing-imports
```

### Tests timeout

```bash
# Run with verbose output
pytest tests/ -v -s --tb=short --timeout=30

# Run single test
pytest tests/unit/test_kalman.py::TestKalmanFilter::test_smoothing_reduces_variance -v
```

### Git merge conflicts

```bash
git status  # See conflicts
# Edit files to resolve
git add .
git commit -m "chore: resolve merge conflicts"
git push
```

---

## Code Review Criteria

**Before submitting, check:**

- ✅ **Correctness:** Code does what docstring promises
- ✅ **Performance:** No N² loops, no blocking operations in hot path
- ✅ **Testability:** Mocking external dependencies, no singletons
- ✅ **Readability:** Variable names self-documenting, <80 lines per function
- ✅ **Safety:** Input validation, graceful error handling, no silent failures
- ✅ **Consistency:** Matches existing code style, uses project conventions

**Reviews will check:**
- Is this feature in the roadmap?
- Are there edge cases you missed?
- Does this add unnecessary complexity?
- Can this be tested more thoroughly?
- Is there performance impact on 5K vans at scale?

---

**Document Version:** 1.0  
**Last Updated:** 2026-03-22
