"""The parse cache's key per source (pipeline/code_keys.py): it changes when code a source's parser
can run changes and not otherwise, it covers every module that code runs, and the cache keeps
every source's current rows."""
import contextlib
import inspect
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import build, code_keys
from pipeline.db import ROOT
from pipeline.providers import PROVIDERS, hyundai_specs
from pipeline.providers.types import ParsedRecord
from tests.helpers import Raws, T, dump, fresh_conn


class Keys(unittest.TestCase):
    """Against a copy of the code, with one file changed at a time."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        shutil.copytree(ROOT / "pipeline", cls.root / "pipeline", ignore=shutil.ignore_patterns("__pycache__"))
        cls.base = code_keys.source_keys(cls.root, PROVIDERS)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def changed_by(self, rel: str) -> set[str]:
        p = self.root / rel
        before = p.read_bytes()
        p.write_bytes(before + b"\n# a comment\n")
        try:
            keys = code_keys.source_keys(self.root, PROVIDERS)
        finally:
            p.write_bytes(before)
        return {n for n in keys if keys[n] != self.base[n]}

    def importers(self, module: str) -> set[str]:
        w = code_keys.Walker(self.root)
        return {n for n, s in code_keys.provider_modules(PROVIDERS).items() if module in w.closure(s)}

    def test_one_reader_changes_only_its_own_key(self):
        self.assertEqual(self.changed_by("pipeline/providers/cinch_used.py"), {"cinch_used"})
        self.assertEqual(self.changed_by("pipeline/providers/whatcar.py"), {"whatcar"})

    def test_a_shared_module_changes_every_importer(self):
        changed = self.changed_by("pipeline/providers/parse.py")
        # carwow_deals imports it; cinch_used only through carwow_deals
        self.assertLessEqual({"carwow_deals", "evdb", "parkers", "cinch_used", "motorpoint_used"}, changed)
        self.assertNotIn("cinch_new", changed)
        self.assertEqual(changed, self.importers("pipeline.providers.parse"))

    def test_an_import_inside_a_function_counts(self):
        # evdb_cars imports services.facts inside a function; facts imports normalise
        self.assertIn("evdb_cars", self.changed_by("pipeline/services/facts.py"))
        changed = self.changed_by("pipeline/normalise.py")
        self.assertLessEqual({"evdb_cars", "cinch_used", "ncd"}, changed)   # cinch_used through used_match
        self.assertNotIn("carwow_deals", changed)
        self.assertEqual(changed, self.importers("pipeline.normalise"))

    def test_packages_count_and_the_registry_does_not(self):
        self.assertEqual(self.changed_by("pipeline/__init__.py"), set(PROVIDERS))
        self.assertEqual(self.changed_by("pipeline/services/__init__.py"), self.importers("pipeline.services"))
        self.assertIn("carwow_specs", self.importers("pipeline.services"))
        self.assertEqual(self.changed_by("pipeline/providers/__init__.py"), set())

    def test_the_pdf_reader_is_in_the_key_of_every_source_reading_pdfs(self):
        self.assertEqual(self.changed_by("pipeline/providers/hyundai_specs.py"), {"hyundai_specs", "adac"})
        saved = hyundai_specs._READER
        hyundai_specs._READER = ("poppler 0.0.0", None)
        try:
            keys = code_keys.source_keys(self.root, PROVIDERS)
        finally:
            hyundai_specs._READER = saved
        self.assertEqual({n for n in keys if keys[n] != self.base[n]}, {"hyundai_specs", "adac"})

    def test_the_parse_path_is_in_every_key(self):
        keys = code_keys.source_keys(self.root, PROVIDERS, b"another parse_entry")
        self.assertEqual({n for n in keys if keys[n] != self.base[n]}, set(PROVIDERS))
        self.assertEqual(build.code_versions(), code_keys.source_keys(
            ROOT, PROVIDERS, "".join(inspect.getsource(f) for f in build.PARSE_PATH).encode()))

    def test_relative_and_computed_imports(self):
        mod = self.root / "pipeline" / "providers" / "zz_probe.py"
        mod.write_text("from . import parse\nfrom ..services import features\nimport importlib\n"
                       "def f():\n    importlib.import_module('pipeline.services.facts')\n", encoding="utf-8")
        try:
            w = code_keys.Walker(self.root)
            self.assertEqual(w.imports("pipeline.providers.zz_probe"),
                             {"pipeline.providers.parse", "pipeline.services.features", "pipeline.services.facts"})
            mod.write_text("import importlib\nname = 'pipeline.services.facts'\nimportlib.import_module(name)\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                code_keys.Walker(self.root).imports("pipeline.providers.zz_probe")
        finally:
            mod.unlink()


# In a fresh interpreter, with the registry (which imports every provider) left out: for each provider,
# the pipeline modules that importing its own loads.
IMPORTS = """
import importlib, json, sys, types
starts = json.loads(sys.argv[1])
out = {}
for name, mods in starts.items():
    for m in [m for m in sys.modules if m == "pipeline" or m.startswith("pipeline.")]:
        del sys.modules[m]
    import pipeline
    stub = types.ModuleType("pipeline.providers")
    stub.__path__ = [pipeline.__path__[0] + "/providers"]
    sys.modules["pipeline.providers"] = pipeline.providers = stub
    for m in mods:
        importlib.import_module(m)
    out[name] = sorted(m for m in sys.modules if (m == "pipeline" or m.startswith("pipeline.")) and m != "pipeline.providers")
print(json.dumps(out))
"""


def _flat(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from _flat(t)
        else:
            yield t


class Coverage(unittest.TestCase):
    """Every pipeline module a source's parse can run is in its key: what importing the provider loads,
    and what runs under its code while every other test runs. The walk decides the key; these check it
    against what runs."""

    @classmethod
    def setUpClass(cls):
        w = code_keys.Walker(ROOT)
        cls.starts = code_keys.provider_modules(PROVIDERS)
        cls.static = {n: w.closure(s) for n, s in cls.starts.items()}

    def test_imports(self):
        run = subprocess.run([sys.executable, "-c", IMPORTS, json.dumps({n: sorted(s) for n, s in self.starts.items()})],
                             cwd=ROOT, capture_output=True, text=True, check=True)
        loaded = json.loads(run.stdout)
        self.assertEqual(set(loaded), set(PROVIDERS))
        for name, mods in loaded.items():
            self.assertLessEqual(set(mods), self.static[name], name)
            self.assertLessEqual(self.starts[name], set(mods), name)

    @unittest.skipUnless(hasattr(sys, "monitoring"), "needs Python 3.12's sys.monitoring")
    def test_what_each_provider_runs(self):
        """While any function of a provider's module runs in the other tests (its parser, and the helpers
        tests call it by), the pipeline modules whose code runs: except below a discover, a fetch or any
        function given the run's Context, which hold the database and the raw store a parse never sees."""
        pkg = (ROOT / "pipeline").resolve()
        module_of: dict[str, str | None] = {}

        def module(filename: str) -> str | None:
            if filename not in module_of:
                p = Path(filename).resolve()
                parts = p.relative_to(pkg.parent).with_suffix("").parts if p.is_relative_to(pkg) else None
                module_of[filename] = ".".join(parts[:-1] if parts[-1] == "__init__" else parts) if parts else None
            return module_of[filename]

        owners: dict[str, set[str]] = {}
        for name, mods in self.starts.items():
            for m in mods:
                owners.setdefault(m, set()).add(name)
        fetchers = {getattr(getattr(cap, f), "__code__", None) for p in PROVIDERS.values() for cap in p.capabilities.values()
                    for f in ("discover", "fetch")}
        fetch_side: dict = {}

        def fetching(code) -> bool:
            if code not in fetch_side:
                fetch_side[code] = code in fetchers or "ctx" in code.co_varnames[:code.co_argcount]
            return fetch_side[code]

        ran: dict[str, set[str]] = {n: set() for n in PROVIDERS}
        active: list = []   # (code, the providers whose code is running, or () below a discover or fetch), innermost last
        mon = sys.monitoring
        DISABLE = mon.DISABLE

        def enter(code, *_):
            m = module(code.co_filename)
            if m is None:
                return DISABLE
            outer = active[-1][1] if active else None
            for n in outer or ():
                ran[n].add(m)
            if fetching(code) or (m in owners and outer == ()):
                active.append((code, ()))
            elif m in owners:
                names = (outer or frozenset()) | owners[m]
                active.append((code, names))
                for n in names:
                    ran[n].add(m)

        def leave(code, *_):
            if active and active[-1][0] is code:
                active.pop()
            elif module(code.co_filename) not in owners and not fetching(code):
                return DISABLE

        def unwind(code, *_):
            if active and active[-1][0] is code:
                active.pop()

        ev = mon.events
        tool = next(i for i in range(6) if mon.get_tool(i) is None)
        mon.use_tool_id(tool, "parse-cache coverage")
        for e, f in ((ev.PY_START, enter), (ev.PY_RESUME, enter), (ev.PY_THROW, enter),
                     (ev.PY_RETURN, leave), (ev.PY_YIELD, leave), (ev.PY_UNWIND, unwind)):
            mon.register_callback(tool, e, f)
        # Discovered as this run was (`-t .` or not), so the modules already loaded are the ones run.
        top = ROOT if __name__.startswith("tests.") else ROOT / "tests"
        others = unittest.TestSuite(t for t in _flat(unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(top)))
                                    if type(t).__module__.rpartition(".")[2] != __name__.rpartition(".")[2])
        mon.set_events(tool, ev.PY_START | ev.PY_RESUME | ev.PY_THROW | ev.PY_RETURN | ev.PY_YIELD | ev.PY_UNWIND)
        try:
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                others.run(unittest.TestResult())
        finally:
            mon.set_events(tool, 0)
            mon.free_tool_id(tool)
            mon.restart_events()

        for name in sorted(PROVIDERS):
            with self.subTest(source=name):
                self.assertLessEqual(self.starts[name], ran[name], "no test runs this provider's code")
                self.assertLessEqual(ran[name], self.static[name])


class Cleanup(unittest.TestCase):
    def test_close_keeps_every_current_key(self):
        rec = [ParsedRecord(kind="spec", key="k", row={"a": 1})]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sub" / "cache.sqlite"
            c = build.ParseCache(path)
            for fetch, code in (("f1", "a-new"), ("f2", "b-new"), ("f1", "a-old"), ("f3", "gone")):
                c.put(fetch, code, rec)
            c.close()   # a build that never reached the raws drops nothing
            c = build.ParseCache(path)
            self.assertEqual(c.get("f3", "gone"), rec)
            c.keep({"a-new", "b-new"})
            c.close()
            c = build.ParseCache(path)
            self.assertEqual([c.get("f1", "a-new"), c.get("f2", "b-new")], [rec, rec])
            self.assertEqual([c.get("f1", "a-old"), c.get("f3", "gone")], [None, None])
            c.close()

    def test_a_changed_reader_reparses_only_its_own_pages(self):
        with Raws() as raws, tempfile.TemporaryDirectory() as d:
            raws.add("carwow_specs", "hyundai/ioniq-3", "carwow_hyundai_ioniq-3_specifications.html", at=T)
            raws.add("carwow_deals", "hyundai/ioniq-3", "carwow_hyundai_ioniq-3_deals.html", at=T)
            path = Path(d) / "cache.sqlite"

            def run():
                cache = build.ParseCache(path)
                try:
                    conn = fresh_conn()
                    report = build.Build(conn, raws.store, cache=cache).run()
                finally:
                    cache.close()
                return (report.parsed, report.from_cache), dump(conn)

            cold, cold_rows = run()
            warm, warm_rows = run()
            self.assertEqual((cold, warm), ((2, 0), (0, 2)))
            self.assertEqual(cold_rows, warm_rows)
            versions = build.code_versions()
            with mock.patch.object(build, "code_versions", lambda root=ROOT: {**versions, "carwow_deals": "changed"}):
                changed, changed_rows = run()
            self.assertEqual(changed, (1, 1))
            self.assertEqual(changed_rows, cold_rows)
            again, _ = run()   # carwow_deals is back on its old code, whose rows that build dropped
            self.assertEqual(again, (1, 1))


if __name__ == "__main__":
    unittest.main()
