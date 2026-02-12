from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class TrajectoryTable:
    meta_lines: list[str]          # lines starting with '#', WITHOUT trailing newline
    header: list[str]              # column names
    rows: list[dict[str, str]]     # string values by column name


def read_trajectory_csv(path: Path) -> TrajectoryTable:
    """Read a trajectory.csv with optional leading '# ...' metadata lines."""
    path = Path(path)
    meta: list[str] = []

    with path.open("r", encoding="utf-8", newline="") as f:
        # metadata
        pos = f.tell()
        line = f.readline()
        while line.startswith("#"):
            meta.append(line.rstrip("\n"))
            pos = f.tell()
            line = f.readline()

        # rewind to the first non-meta line
        f.seek(pos)

        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        rows: list[dict[str, str]] = []
        for r in reader:
            if r is None:
                continue
            # DictReader may yield None keys in malformed rows; ignore them.
            rr = {k: ("" if v is None else str(v)) for k, v in r.items() if k is not None}
            if not rr:
                continue
            rows.append(rr)

    return TrajectoryTable(meta_lines=meta, header=header, rows=rows)


def write_trajectory_csv_atomic(
    path: Path,
    meta_lines: Iterable[str],
    header: list[str],
    rows: Iterable[dict[str, str]],
) -> None:
    """Write trajectory.csv via temp file + replace (atomic on same filesystem)."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")

    with tmp.open("w", encoding="utf-8", newline="") as f:
        for line in meta_lines:
            line = str(line).rstrip("\n")
            if not line.startswith("#"):
                line = "# " + line
            f.write(line + "\n")

        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            # Ensure every header column exists (DictWriter will fill missing with '')
            rr = {k: ("" if r.get(k) is None else str(r.get(k))) for k in header}
            w.writerow(rr)

    tmp.replace(path)
