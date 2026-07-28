import os
import sys

# tests/ has no __init__.py, so pytest's own import-path resolution stops
# there and never adds backend/ to sys.path. Every test does a flat
# `import config` / `import enrich` / `from analysis import ...` expecting
# backend/ itself to be on sys.path, so add it explicitly here regardless of
# how pytest is invoked (bare `pytest`, an IDE runner, a different cwd, ...).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
