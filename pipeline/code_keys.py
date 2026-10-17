"""Each source's key in the build's parse cache: what its parsed records depend on.

A source's key hashes the code its parser can run and what that code reads besides itself:
    the module that defines the provider, and every `pipeline` module it imports, directly or
        through others, found from its import statements (those inside functions too), with the
        packages they sit in
    what a module in that set reads that is not Python code, from the module's `parser_inputs()`
        (hyundai_specs: which PDF reader, and its version)
    the Python version, and the build's own parse path (`extra`)
So a change to one reader re-parses only its own source's pages, and a change to a shared module
re-parses every source that imports it.

The registry (pipeline/providers/__init__.py) imports every provider, so it is followed only where
a module imports it by name, not as the package every provider sits in.
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import sys
from pathlib import Path

REGISTRY = "pipeline.providers"
HOOK = "parser_inputs"


def module_file(root: Path, name: str) -> Path | None:
    base = Path(root).joinpath(*name.split("."))
    for p in (base.with_suffix(".py"), base / "__init__.py"):
        if p.is_file():
            return p
    return None


class Walker:
    """The import graph of the `pipeline` package under `root`, read from the files."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._imports: dict[str, set[str]] = {}
        self._hooked: dict[str, bool] = {}
        self._bytes: dict[str, bytes] = {}

    def _file(self, name: str) -> Path:
        p = module_file(self.root, name)
        if p is None:
            raise ValueError(f"no module {name} under {self.root}")
        return p

    def source(self, name: str) -> bytes:
        if name not in self._bytes:
            self._bytes[name] = self._file(name).read_bytes().replace(b"\r\n", b"\n")
        return self._bytes[name]

    def imports(self, name: str) -> set[str]:
        """The `pipeline` modules one module's import statements name, wherever in the file they are."""
        if name in self._imports:
            return self._imports[name]
        path = self._file(name)
        tree = ast.parse(self.source(name), str(path))
        package = name if path.name == "__init__.py" else name.rpartition(".")[0]
        out: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                out.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = package.split(".")[:len(package.split(".")) - node.level + 1]
                    mod = ".".join(base + ([node.module] if node.module else []))
                else:
                    mod = node.module or ""
                subs = {f"{mod}.{a.name}" for a in node.names if module_file(self.root, f"{mod}.{a.name}")}
                out.update(subs)
                if len(subs) < len(node.names):
                    out.add(mod)   # a name the module itself defines
            elif isinstance(node, ast.Call) and _is_dynamic_import(node.func):
                arg = node.args[0] if node.args else None
                if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                    raise ValueError(f"{path}:{node.lineno}: an import by a computed name cannot be keyed")
                out.add(arg.value)
        self._imports[name] = {m for m in out if m == "pipeline" or m.startswith("pipeline.")}
        return self._imports[name]

    def closure(self, starts: set[str]) -> set[str]:
        """`starts` and every module they import, directly or through others, with the packages they sit in
        (whose __init__ runs on import), except the registry as a package."""
        seen: set[str] = set()
        todo = list(starts)
        while todo:
            m = todo.pop()
            if m in seen:
                continue
            seen.add(m)
            parts = m.split(".")
            todo += [p for p in (".".join(parts[:i]) for i in range(1, len(parts))) if p != REGISTRY]
            todo += self.imports(m)
        return seen

    def hooked(self, name: str) -> bool:
        """Whether the module defines `parser_inputs()` at its top level."""
        if name not in self._hooked:
            tree = ast.parse(self.source(name))
            self._hooked[name] = any(isinstance(n, ast.FunctionDef) and n.name == HOOK for n in tree.body)
        return self._hooked[name]


def _is_dynamic_import(f: ast.expr) -> bool:
    return (isinstance(f, ast.Name) and f.id in ("__import__", "import_module")) or \
        (isinstance(f, ast.Attribute) and f.attr == "import_module")


def provider_modules(providers: dict) -> dict[str, set[str]]:
    """Source name -> the modules its parser starts from: the one defining the provider, and each
    capability's parse function's own."""
    out: dict[str, set[str]] = {}
    loaded = [(n, m) for n, m in list(sys.modules.items()) if n.startswith(REGISTRY + ".") and m is not None]
    for name, p in providers.items():
        mods = {n for n, m in loaded if getattr(m, "provider", None) is p}
        if not mods:
            raise ValueError(f"no module defines the provider {name}")
        for cap in p.capabilities.values():
            fn = getattr(cap.parse, "func", cap.parse)   # a functools.partial's function
            mods.add(fn.__module__)
        out[name] = mods
    return out


def source_keys(root: Path, providers: dict, extra: bytes = b"") -> dict[str, str]:
    """Source name -> its parse-cache key."""
    w = Walker(root)
    inputs: dict[str, str] = {}
    out = {}
    for name, starts in sorted(provider_modules(providers).items()):
        h = hashlib.sha256(f"python {sys.version_info[0]}.{sys.version_info[1]}\n".encode() + extra)
        for m in sorted(w.closure(starts)):
            h.update(f"\0{m}\0".encode() + w.source(m))
            if w.hooked(m):
                if m not in inputs:
                    inputs[m] = str(getattr(importlib.import_module(m), HOOK)())
                h.update(f"\0{m}.{HOOK}\0{inputs[m]}".encode())
        out[name] = h.hexdigest()[:16]
    return out
