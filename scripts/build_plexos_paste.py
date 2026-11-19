"""Add the final RHS adders to the PLEXOS RHS expressions exported to inputs/rhs_adjust/*.txt and write files that can be
pasted straight back into the PLEXOS data grid.

Each exported row is a tab-separated, fully quoted line whose Expression cell is a reverse-Polish list, one term per line
(`1 -40.45 MUL ADD`). For every (constraint, timeslice) in outputs/FINAL/esoo_equation_edits.csv this script appends one line
    1 <adder MW> MUL ADD
at the end of that row's expression. Because it is the last operation it adds the adder to the finished RHS (after any
earlier scaling), the same form the exports already use for constants. All rows are written in the original order (changed rows carry
the adder, the rest are unchanged), so the whole file can be selected and pasted. Files keep the export format: UTF-8, CRLF, tab separated, all cells quoted.
Output: outputs/FINAL/plexos_paste/<same file name>, plus plexos_paste_summary.csv.
Run: .venv\\Scripts\\python.exe -X utf8 -I scripts\\build_plexos_paste.py"""
import csv
import io
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "inputs" / "rhs_adjust"
OUT = ROOT / "outputs" / "FINAL" / "plexos_paste"
OUT.mkdir(parents=True, exist_ok=True)
CHILD, TIMESLICE, EXPR = 2, 10, 12


def parse(b: bytes):
    t = b.decode("utf-8")
    return list(csv.reader(io.StringIO(t, newline=""), delimiter="\t", quotechar='"'))


def serialise(rows) -> bytes:
    buf = io.StringIO(newline="")
    buf.write("\t".join(rows[0]) + "\r\n")                    # exports leave the header row unquoted
    w = csv.writer(buf, delimiter="\t", quotechar='"', quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    w.writerows(rows[1:])
    return buf.getvalue().rstrip("\r\n").encode("utf-8")      # exports have no trailing newline


edits = pl.read_csv(ROOT / "outputs" / "FINAL" / "esoo_equation_edits.csv", infer_schema_length=None)
amount = {(r["constraint"], r["timeslice"]): float(r["add_to_rhs_constant_mw"]) for r in edits.iter_rows(named=True)}

summary, used = [], set()
for f in sorted(SRC.glob("*.txt")):
    raw = f.read_bytes()
    rows = parse(raw)
    header, body = rows[0], rows[1:]
    if serialise(rows) != raw:
        raise SystemExit(f"{f.name}: re-serialising the export does not reproduce it byte for byte; stopping")
    changed, full = [], []
    for r in body:
        key = (r[CHILD], r[TIMESLICE])
        if key not in amount:
            full.append(r)
            continue
        used.add(key)
        mw = amount[key]
        line = f"1 {mw:g} MUL ADD"
        core = r[EXPR].rstrip("\r\n")
        tail = r[EXPR][len(core):] or "\r\n"
        new = list(r)
        new[EXPR] = core + "\r\n" + line + tail
        changed.append(new)
        full.append(new)
        summary.append({"file": f.name, "constraint": key[0], "timeslice": key[1], "adder_mw": mw, "line_added": line,
                        "previous_last_line": core.split("\r\n")[-1]})
    if changed:
        (OUT / f.name).write_bytes(serialise([header] + full))     # every row, original order
        # verify: reparse; same rows in the same order; changed rows = original + exactly one extra line; others identical
        chk = parse((OUT / f.name).read_bytes())[1:]
        assert len(chk) == len(body)
        for n, o in zip(chk, body):
            assert [x for i, x in enumerate(n) if i != EXPR] == [x for i, x in enumerate(o) if i != EXPR]
            if (o[CHILD], o[TIMESLICE]) in amount:
                assert n[EXPR].startswith(o[EXPR].rstrip("\r\n")) and n[EXPR].count("\n") == o[EXPR].count("\n") + 1
            else:
                assert n[EXPR] == o[EXPR]
    print(f"{f.name}: {len(body)} rows written, {len(changed)} with an adder added")

missing = sorted(set(amount) - used)
pl.DataFrame(summary).write_csv(OUT / "plexos_paste_summary.csv")
print("edit rows applied:", len(used), "of", len(amount))
print("edit rows with no matching row in the exports:", missing)
