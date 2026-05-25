# Tests

Pytest suite scaffold. Run with:

```bash
pip install pytest
pytest tests/ -v
```

## Planned coverage
- `test_models.py` — Pydantic schema validation (TestCase, TestSession)
- `test_db.py` — SQLite CRUD round-trip
- `test_generator.py` — mock LLM, verify shape of generated cases
- `test_executor.py` — mock driver, verify metrics aggregation
- `test_routes.py` — Flask test client, hit each endpoint
