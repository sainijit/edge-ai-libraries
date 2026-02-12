# Semantic Comparison Service

AI-powered semantic comparison service for item matching and validation. Consolidates semantic matching logic from multiple applications into a single, extensible, production-ready microservice.

## Features

- **Multiple Matching Strategies**:
  - Exact matching (fast string comparison)
  - Semantic matching (VLM/LLM-based)
  - Hybrid matching (exact first, semantic fallback)

- **Flexible VLM Backends**:
  - OVMS (OpenVINO Model Server) - GPU-accelerated, supports batching
  - OpenVINO GenAI (local) - In-process inference
  - OpenAI API (cloud fallback)

- **Production-Ready**:
  - FastAPI with async support
  - Pydantic models for validation
  - Structured logging
  - Prometheus metrics
  - Health checks
  - Response caching (memory/Redis)

- **Comprehensive Testing**:
  - Unit tests for all components
  - Integration tests for API endpoints
  - 80%+ code coverage

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (optional)
- OVMS with VLM model deployed (if using OVMS backend)

### Local Development

1. **Clone and setup**:
```bash
cd semantic-search-agent
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. **Configure**:
```bash
cp .env.example .env
# Edit .env with your settings
```

3. **Run service**:
```bash
uvicorn app.main:app --reload --port 8080
```

4. **Test**:
```bash
# Run tests
pytest

# With coverage
pytest --cov=app --cov-report=html

# Access API docs
open http://localhost:8080/docs
```

### Docker Deployment

1. **Build and run**:
```bash
cd docker
docker-compose up -d
```

2. **Check health**:
```bash
curl http://localhost:8080/api/v1/health
```

3. **View logs**:
```bash
docker-compose logs -f semantic-service
```

## API Usage

### Order Validation

Compare expected vs detected items:

```bash
curl -X POST http://localhost:8080/api/v1/compare/order \
  -H "Content-Type: application/json" \
  -d '{
    "expected_items": [
      {"name": "apple", "quantity": 2},
      {"name": "banana", "quantity": 1}
    ],
    "detected_items": [
      {"name": "green apple", "quantity": 2},
      {"name": "orange", "quantity": 1}
    ],
    "options": {
      "use_semantic": true
    }
  }'
```

Response:
```json
{
  "status": "mismatch",
  "validation": {
    "missing": [
      {"name": "banana", "quantity": 1}
    ],
    "extra": [
      {"name": "orange", "quantity": 1}
    ],
    "quantity_mismatch": [],
    "matched": [
      {
        "expected": {"name": "apple", "quantity": 2},
        "detected": {"name": "green apple", "quantity": 2},
        "match_type": "hybrid_semantic",
        "confidence": 0.95
      }
    ]
  },
  "metrics": {
    "total_expected": 2,
    "total_detected": 2,
    "exact_matches": 0,
    "semantic_matches": 1,
    "processing_time_ms": 145.67
  }
}
```

### Inventory Validation

Check if items exist in inventory:

```bash
curl -X POST http://localhost:8080/api/v1/compare/inventory \
  -H "Content-Type: application/json" \
  -d '{
    "items": ["coca cola", "bread", "unknown item"],
    "options": {
      "use_semantic": true
    }
  }'
```

### Semantic Match

Generic semantic comparison:

```bash
curl -X POST http://localhost:8080/api/v1/compare/semantic \
  -H "Content-Type: application/json" \
  -d '{
    "text1": "green apple",
    "text2": "apple",
    "context": "grocery products"
  }'
```

## Configuration

### Environment Variables

Key settings in `.env`:

```bash
# VLM Backend
VLM_BACKEND=ovms  # Options: ovms, openvino_local, openai

# OVMS Configuration
OVMS_ENDPOINT=http://ovms-vlm:8000
OVMS_MODEL_NAME=Qwen2-VL-2B-Instruct

# Caching
CACHE_ENABLED=true
CACHE_BACKEND=memory  # Options: memory, redis

# Matching
DEFAULT_MATCHING_STRATEGY=hybrid  # Options: exact, semantic, hybrid
CONFIDENCE_THRESHOLD=0.85
```

### Config Files

- `config/service_config.yaml` - Service configuration
- `config/orders.json` - Expected orders database
- `config/inventory.json` - Inventory items list

## Architecture

```
app/
├── main.py                 # FastAPI application
├── api/
│   ├── routes.py          # API endpoints
│   ├── models.py          # Pydantic models
│   └── dependencies.py    # Dependency injection
├── core/
│   ├── config.py          # Configuration management
│   ├── logger.py          # Structured logging
│   └── metrics.py         # Prometheus metrics
├── services/
│   ├── comparison_engine.py  # Core comparison logic
│   ├── matchers/
│   │   ├── base.py        # BaseMatcher interface
│   │   ├── exact.py       # Exact matching
│   │   ├── semantic.py    # Semantic matching
│   │   └── hybrid.py      # Hybrid strategy
│   └── vlm/
│       ├── base.py        # BaseVLMBackend interface
│       ├── ovms.py        # OVMS backend
│       ├── openvino_local.py  # OpenVINO local
│       └── openai.py      # OpenAI API
└── utils/
    ├── __init__.py        # Text utilities
    └── cache.py           # Caching layer
```

## Integration Examples

### Order Accuracy Application

Replace direct VLM calls with service API:

```python
import httpx

response = httpx.post(
    "http://semantic-service:8080/api/v1/compare/order",
    json={
        "expected_items": expected_items,
        "detected_items": detected_items,
        "options": {"use_semantic": True}
    },
    timeout=30.0
)
validation = response.json()
```

### Loss Prevention Application

Replace inventory set matching:

```python
import httpx

response = httpx.post(
    "http://semantic-service:8080/api/v1/compare/inventory",
    json={
        "items": [item_name],
        "options": {"use_semantic": True}
    },
    timeout=10.0
)
result = response.json()["results"][0]
match = result["match"]
```

## Monitoring

### Prometheus Metrics

Access metrics at `http://localhost:9090/metrics`:

- `api_requests_total` - Total API requests by endpoint/status
- `matches_total` - Total matches by type/result
- `request_duration_seconds` - Request latency histogram
- `vlm_inference_duration_seconds` - VLM inference time
- `cache_hits_total` / `cache_misses_total` - Cache performance
- `vlm_backend_available` - VLM backend health

### Structured Logging

JSON logs with contextual information:

```json
{
  "event": "Semantic match",
  "text1": "apple",
  "text2": "green apple",
  "match": true,
  "confidence": 0.95,
  "timestamp": "2026-01-30T10:30:45.123Z"
}
```

## Testing

Run full test suite:

```bash
# All tests
pytest

# Specific test file
pytest tests/test_matchers.py

# With coverage
pytest --cov=app --cov-report=html

# Verbose output
pytest -v
```

## Performance

### Benchmarks

- **Exact matching**: < 5ms per comparison
- **Semantic matching**: < 100ms per comparison (OVMS)
- **Throughput**: > 50 req/s (exact), > 10 req/s (semantic)
- **Cache hit rate**: 80%+ for repeated queries

### Optimization Tips

1. Enable caching for repeated queries
2. Use hybrid matcher (exact first, semantic fallback)
3. Use OVMS with continuous batching for high throughput
4. Tune `CONFIDENCE_THRESHOLD` to reduce false positives

## Troubleshooting

### VLM Backend Not Available

Check OVMS endpoint:
```bash
curl http://ovms-vlm:8000/v1/models
```

### High Latency

1. Check VLM backend latency in metrics
2. Enable caching: `CACHE_ENABLED=true`
3. Use exact matching first: `DEFAULT_MATCHING_STRATEGY=hybrid`

### Memory Issues

1. Use Redis for caching: `CACHE_BACKEND=redis`
2. Reduce cache TTL: `CACHE_TTL=1800`
3. Limit concurrent requests

## License

Copyright (c) 2026 Intel Corporation

## Support

For issues and questions, contact Intel AI Team.
