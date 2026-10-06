"""Shared test plumbing: an in-memory pipeline run over the real seed and pastes."""
from pipeline.db import ROOT, connect, init_schema
from pipeline.providers import PROVIDERS
from pipeline.providers.types import Context
from pipeline.runner import run


def fresh_conn():
    conn = connect(":memory:")
    init_schema(conn)
    return conn


def run_all(conn, providers=None):
    ctx = Context(root=ROOT)
    results = []
    for p in (providers or PROVIDERS.values()):
        for cap in p.capabilities:
            results.append(run(conn, p, cap, ctx=ctx))
    return results
