"""Migration backward-compatibility check for CI (TD §16 rolling deploys, §17 test layers).

During a rolling deploy the previous release's code keeps running against the already-migrated database for a while (readiness
reports the schema as "ahead" and still serves). So a release's migrations must be additive: the previous code must keep working.
This static check reads the ``upgrade()`` of migration files and flags what would break the previous release:

- NOT_NULL_WITHOUT_DEFAULT  add_column / alter_column(nullable=False) without a server_default: the old code's INSERTs omit the column
- DROP_COLUMN, DROP_TABLE   the old code still reads and writes it
- RENAME_COLUMN, RENAME_TABLE
- DROP_CONSTRAINT_UNIQUE    (a dropped unique constraint is fine for old code, but a *new* one is checked at review, not here)

A contract-phase change that is deliberate (the previous release no longer uses the column) is acknowledged with a comment
``# compat: <reason>`` in the file. Usage:

    python -m app.pic.tools.check_migrations                    # every migration
    python -m app.pic.tools.check_migrations --base origin/main # only migrations added since that git ref (CI on pull requests)
"""
import argparse
import ast
import subprocess
import sys
from pathlib import Path

from app.pic.config import BACKEND_DIR

VERSIONS = BACKEND_DIR / "pic_migrations" / "versions"
DROPS = {"drop_column": "DROP_COLUMN", "drop_table": "DROP_TABLE", "rename_table": "RENAME_TABLE"}


def _kw(call: ast.Call, name: str):
    return next((k.value for k in call.keywords if k.arg == name), None)


def _is_false(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is False


def _column_problem(column: ast.AST):
    """NOT NULL without a server default in a ``sa.Column(...)`` call."""
    if not (isinstance(column, ast.Call) and getattr(column.func, "attr", "") == "Column"):
        return None
    if _is_false(_kw(column, "nullable")) and _kw(column, "server_default") is None and _kw(column, "primary_key") is None \
            and _kw(column, "autoincrement") is None and _kw(column, "sa_identity") is None:
        name = column.args[0].value if column.args and isinstance(column.args[0], ast.Constant) else "?"
        return name
    return None


def check_file(path: Path) -> list[dict]:
    """Problems in one migration file ([] when it is backward compatible or carries a ``# compat:`` acknowledgement)."""
    source = Path(path).read_text(encoding="utf-8")
    if "# compat:" in source:
        return []
    tree = ast.parse(source)
    problems = []
    for func in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "upgrade"):
        for call in (n for n in ast.walk(func) if isinstance(n, ast.Call)):
            target = call.func
            if not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "op"):
                continue
            op = target.attr
            where = {"file": Path(path).name, "line": call.lineno}
            if op == "add_column" and len(call.args) >= 2:
                column = _column_problem(call.args[1])
                if column:
                    problems.append({**where, "kind": "NOT_NULL_WITHOUT_DEFAULT", "detail": f"{call.args[0].value}.{column} is NOT NULL without server_default"})
            elif op == "alter_column":
                table = call.args[0].value if call.args and isinstance(call.args[0], ast.Constant) else "?"
                column = call.args[1].value if len(call.args) > 1 and isinstance(call.args[1], ast.Constant) else "?"
                if _kw(call, "new_column_name") is not None:
                    problems.append({**where, "kind": "RENAME_COLUMN", "detail": f"{table}.{column} is renamed"})
                if _is_false(_kw(call, "nullable")) and _kw(call, "server_default") is None:
                    problems.append({**where, "kind": "NOT_NULL_WITHOUT_DEFAULT", "detail": f"{table}.{column} becomes NOT NULL without server_default"})
            elif op in DROPS:
                what = ".".join(str(a.value) for a in call.args[:2] if isinstance(a, ast.Constant))
                problems.append({**where, "kind": DROPS[op], "detail": what})
    return problems


def check(versions: Path = VERSIONS, base: str | None = None) -> list[dict]:
    files = sorted(Path(versions).glob("[0-9]*.py"))
    if base:
        added = subprocess.run(["git", "diff", "--name-only", "--diff-filter=A", base, "--", str(versions)], capture_output=True, text=True,
                               cwd=BACKEND_DIR).stdout.split()
        names = {Path(a).name for a in added}
        files = [f for f in files if f.name in names]
    problems = []
    for f in files:
        problems += check_file(f)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", help="git ref: only migrations added since it are checked")
    args = parser.parse_args(argv)
    problems = check(base=args.base)
    for p in problems:
        print(f"{p['file']}:{p['line']}: {p['kind']}: {p['detail']}")
    print(f"{len(problems)} backward-compatibility problem(s)" if problems else "migrations are backward compatible with the previous release")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
