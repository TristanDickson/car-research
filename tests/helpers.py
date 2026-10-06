"""Shared test plumbing: an in-memory pipeline run over the real seed and pastes.

Only offline providers run by default; live scrapers are exercised against
fixtures in tests/test_providers.py, never over the network.
"""
from pipeline.db import ROOT, connect, init_schema
from pipeline.providers import PROVIDERS
from pipeline.providers.types import Context
from pipeline.runner import run


def fresh_conn():
    conn = connect(":memory:")
    init_schema(conn)
    return conn


def offline_providers():
    return [p for p in PROVIDERS.values() if not p.live]


def run_all(conn, providers=None):
    ctx = Context(root=ROOT)
    results = []
    for p in (providers or offline_providers()):
        for cap in p.capabilities:
            results.append(run(conn, p, cap, ctx=ctx))
    return results
