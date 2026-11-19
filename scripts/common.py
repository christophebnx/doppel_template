"""Shared helpers for doppel scripts: repo root, config, time, ISO weeks, markdown frontmatter, tasks.

All date/time values are naive local times in the configured timezone (config.yaml: timezone).
"""
from __future__ import annotations

import datetime as dt
import math
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TZ = "Europe/Brussels"
DEFAULT_CAPACITY = {
    "estimate_correction": 1.0,  # the planning module (docs/extending.md) adds hours_per_week, max_load, …
}
OPEN_STATUSES = ("clarify", "todo", "doing", "blocked", "waiting")
NO_CAPACITY_STATUSES = ("waiting",)  # open but consuming no owner time (someone else must deliver)
CLOSED_STATUSES = ("done", "dropped")
QUANTUM_MIN = 15  # time granularity in minutes

# --------------------------------------------------------------------------- root & config


def get_root(arg: str | Path | None = None) -> Path:
    """Repo root: --root arg, else $DOPPEL_ROOT, else the directory above scripts/."""
    if arg:
        return Path(arg).resolve()
    env = os.environ.get("DOPPEL_ROOT")
    return Path(env).resolve() if env else REPO_ROOT


def load_config(root: Path) -> dict:
    path = root / "config.yaml"
    cfg = (yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None) or {}
    cfg["capacity"] = {**DEFAULT_CAPACITY, **(cfg.get("capacity") or {})}
    cfg.setdefault("timezone", DEFAULT_TZ)
    cfg["projects"] = cfg.get("projects") or {}
    return cfg


def write_config_projects(root: Path, projects: dict) -> None:
    """Rewrite only the `projects:` block of config.yaml (must be the last top-level key),
    keeping comments and formatting of everything above it."""
    path = root / "config.yaml"
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^projects:.*$", text, flags=re.M)
    head = text[: m.start()] if m else text.rstrip("\n") + "\n"
    if projects:
        block = "projects:\n" + _indent(dump_yaml(projects, sort_keys=True))
    else:
        block = "projects: {}\n"
    path.write_text(head + block, encoding="utf-8")


def write_config_block(root: Path, key: str, data: dict) -> None:
    """Rewrite one top-level block of config.yaml (from `key:` to the next top-level key), keeping everything else
    (comments included). `projects` must stay last: use write_config_projects for it."""
    if key == "projects":
        return write_config_projects(root, data)
    path = root / "config.yaml"
    text = path.read_text(encoding="utf-8")
    block = f"{key}:\n" + _indent(dump_yaml(data, sort_keys=True)) if data else f"{key}: {{}}\n"
    m = re.search(rf"^{re.escape(key)}:.*?(?=^[A-Za-z_][\w-]*:)", text, flags=re.M | re.S)
    if m:
        text = text[: m.start()] + block + text[m.end():]
    else:  # insert right before `projects:`
        p = re.search(r"^projects:", text, flags=re.M)
        text = (text[: p.start()] + block + text[p.start():]) if p else text.rstrip("\n") + "\n" + block
    path.write_text(text, encoding="utf-8")


def set_config_scalar(root: Path, key: str, value) -> None:
    """Replace the value of an existing `key: value` line in config.yaml (comments preserved)."""
    path = root / "config.yaml"
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(rf"^(\s*{re.escape(key)}:\s*)([^#\n]*?)(\s*(#.*)?)$", re.M)
    if not pattern.search(text):
        raise KeyError(f"{key} not found in config.yaml")
    text = pattern.sub(lambda m: f"{m.group(1)}{value}{m.group(3)}", text, count=1)
    path.write_text(text, encoding="utf-8")


def _indent(s: str, n: int = 2) -> str:
    return "".join((" " * n + line) if line.strip() else line for line in s.splitlines(True))


# --------------------------------------------------------------------------- time


def now(cfg: dict | None = None) -> dt.datetime:
    """Current local time (naive). Override with $DOPPEL_NOW (e.g. '2026-11-23 08:00') for replays/tests."""
    env = os.environ.get("DOPPEL_NOW")
    if env:
        return parse_dt(env)
    tz = ZoneInfo((cfg or {}).get("timezone", DEFAULT_TZ))
    return dt.datetime.now(tz).replace(tzinfo=None, second=0, microsecond=0)


def parse_dt(v) -> dt.datetime:
    if isinstance(v, dt.datetime):
        return v.replace(tzinfo=None)
    if isinstance(v, dt.date):
        return dt.datetime.combine(v, dt.time())
    return dt.datetime.fromisoformat(str(v).strip())


def parse_date(v) -> dt.date | None:
    if v in (None, "", "null"):
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v).strip()[:10])


def fmt_dt(d: dt.datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M")


def hours(minutes: float) -> float:
    return round(minutes / 60, 2)


def ceil_quantum(minutes: float, q: int = QUANTUM_MIN) -> int:
    return int(math.ceil(round(minutes, 6) / q) * q)


# --------------------------------------------------------------------------- ISO weeks

WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")
DAY_INDEX = {
    # english
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
    # french
    "lun": 0, "mar": 1, "mer": 2, "jeu": 3, "ven": 4, "sam": 5, "dim": 6,
    "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3, "vendredi": 4, "samedi": 5, "dimanche": 6,
}
DAY_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def week_of(d: dt.date | dt.datetime) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def parse_week(week: str) -> tuple[int, int]:
    m = WEEK_RE.match(week.strip())
    if not m:
        raise ValueError(f"invalid ISO week '{week}' (expected e.g. 2026-W47)")
    return int(m.group(1)), int(m.group(2))


def week_monday(week: str) -> dt.date:
    y, w = parse_week(week)
    return dt.date.fromisocalendar(y, w, 1)


def week_days(week: str) -> list[dt.date]:
    mon = week_monday(week)
    return [mon + dt.timedelta(days=i) for i in range(7)]


def week_bounds(week: str) -> tuple[dt.datetime, dt.datetime]:
    start = dt.datetime.combine(week_monday(week), dt.time())
    return start, start + dt.timedelta(days=7)


def shift_week(week: str, n: int) -> str:
    return week_of(week_monday(week) + dt.timedelta(weeks=n))


def day_index(name: str) -> int:
    key = name.strip().lower()
    if key not in DAY_INDEX:
        raise ValueError(f"unknown weekday '{name}'")
    return DAY_INDEX[key]


# --------------------------------------------------------------------------- markdown + frontmatter

FM_RE = re.compile(r"\A---\n(.*?)\n---[ \t]*\n?(.*)\Z", re.S)


def read_md(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    m = FM_RE.match(text)
    if not m:
        return {}, text
    return (yaml.safe_load(m.group(1)) or {}), m.group(2)


class _NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):  # never emit &id001 / *id001 anchors
        return True


def dump_yaml(data, **kw) -> str:
    opts = {"sort_keys": False, "allow_unicode": True, "width": 1000, **kw}
    return yaml.dump(data, Dumper=_NoAliasDumper, **opts)


class _FrontmatterDumper(_NoAliasDumper):
    """Block mappings, flow lists: `sources: [a, b]` but never `{date: …, type: …}`."""


_FrontmatterDumper.add_representer(
    list, lambda d, data: d.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True))


def dump_frontmatter(meta: dict) -> str:
    return yaml.dump(meta, Dumper=_FrontmatterDumper, sort_keys=False, allow_unicode=True, width=1000,
                     default_flow_style=False)


def write_md(path: Path, meta: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = body.lstrip("\n")
    path.write_text(f"---\n{dump_frontmatter(meta)}---\n\n{body}", encoding="utf-8")


def slugify(text: str, max_len: int = 40) -> str:
    import unicodedata

    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:max_len].rstrip("-") or "item"


# --------------------------------------------------------------------------- tasks


@dataclass
class Task:
    id: str
    path: Path
    meta: dict = field(default_factory=dict)

    def __getattr__(self, name):  # convenient read access to frontmatter
        meta = self.__dict__.get("meta", {})
        if name in meta:
            return meta[name]
        raise AttributeError(name)

    @property
    def status(self) -> str:
        return self.meta.get("status") or "todo"

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    @property
    def deadline_date(self) -> dt.date | None:
        return parse_date(self.meta.get("deadline"))

    def remaining_h(self, correction: float = 1.0) -> float:
        est = float(self.meta.get("estimate_h") or 0) * correction
        done = float(self.meta.get("actual_h") or 0)
        return round(max(est - done, 0.0), 2)


def load_tasks(root: Path) -> dict[str, Task]:
    tasks = {}
    for p in sorted((root / "tasks").glob("T-*.md")):
        meta, _ = read_md(p)
        tid = meta.get("id") or p.stem
        tasks[tid] = Task(id=tid, path=p, meta=meta)
    return tasks


# --------------------------------------------------------------------------- deterministic signals on crashes


def run_main(main, script_file: str) -> int:
    """Run a script's main(); an uncaught exception becomes a `deterministic` evolution signal, then is re-raised.
    Only the exception type and the frames (file:line function) are recorded — never the message (it may hold data)."""
    try:
        return main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        try:
            import traceback

            from signals import emit

            name = Path(script_file).name
            frames = [f"{Path(f.filename).name}:{f.lineno} {f.name}" for f in traceback.extract_tb(exc.__traceback__)]
            inner = next((fr.split()[-1] for fr in reversed(frames) if fr.startswith(name)), "main")
            argv = " ".join(a for a in sys.argv[1:] if not a.startswith("--root"))[:120]
            emit(get_root(), emitter=f"script:{name}", kind="bug", component=f"scripts/{name}",
                 fingerprint=f"script.{Path(name).stem}.{type(exc).__name__}.{inner}", severity="high",
                 origin="deterministic", evidence=f"{type(exc).__name__}@{frames[-1] if frames else name}",
                 expected="Le script se termine sans exception", observed=f"{type(exc).__name__} non gérée",
                 proofs=[f"uv run scripts/{name} {argv}", "\n".join(frames[-10:])])
        except Exception:  # never mask the original error
            pass
        raise
