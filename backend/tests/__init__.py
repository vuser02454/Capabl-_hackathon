"""Marks backend/tests as a real package.

Needed because a third-party dependency (installed alongside ultralytics) ships its own top-level
`tests` package into site-packages. Without this file, `from tests.test_decision_engine import ...`
resolves to that package instead of this directory and the suite fails to collect.
"""
