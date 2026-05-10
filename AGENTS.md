# Agent Guidelines

- Maintain repository cleanliness by not tracking temporary verification or benchmark scripts (e.g., `benchmark_redis.py`).
- Do not include `.pyc` files or `__pycache__` deletions in commits or patches; let `.gitignore` handle them instead.
- When running Python scripts for testing or verification, you must run `export PYTHONDONTWRITEBYTECODE=1` in your bash session before executing Python code to prevent the generation of `__pycache__` directories and `.pyc` files.
