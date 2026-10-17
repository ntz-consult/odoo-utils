#!/usr/bin/env python3
"""Per-project port pools for local Odoo checkouts.

A register (TOML) gives every project its own non-overlapping blocks of ports:

    version = 1
    public_offset = 10000     # informational: public proxy port = http + offset
    gevent_offset = 500       # second (gevent/websocket) port = http + offset
    work_root = "~/Work"      # checkouts scanned for claimed ports

    [projects.example]
    main = 8100                         # main checkout http port (optional)
    main_test = [9100, 9201]            # main checkout test-port range (optional)
    worktrees = [8300, 8349]            # http ports for linked worktrees
    worktree_tests = [24000, 25999]     # test ports for linked worktrees
    test_block = 40                     # test ports per worktree
    remove_hook = "cmd"                 # optional: run by odoo-worktree-remove

Worktree slot n uses http = worktrees[0] + n, gevent = http + gevent_offset and
tests worktree_tests[0] + n * test_block .. + test_block - 1.

The register path is $ODOO_PORTS_REGISTER, else ~/Work/sys-admin/odoo/ports.toml.
When the default register does not exist nothing is enforced; an explicitly
configured register that does not exist is an error.

Commands:
    ports.py show                         print the pools and current claims
    ports.py allocate PROJECT [--root R]  first free worktree slot (preview, shell exports)
    ports.py assign PROJECT --root R --db DB [--http P] [--test-start S]
                                          allocate or take the given slot and write
                                          R/.odoo/worktree.toml, under the port lock
    ports.py guard --root R               refuse a linked worktree without its own ports
    ports.py check PROJECT --root R --http P [--gevent G] [--test S E]
    ports.py slot PROJECT --http P        canonical worktree slot of an http port
    ports.py gevent PROJECT --http P      gevent port for an http port
    ports.py active                       register path; exit 3 when none is in use
    ports.py hook PROJECT                 the pool's remove_hook (odoo-worktree-remove)

A linked worktree with its own .odoo directory never inherits the primary checkout's
ports: the committed config.toml carries the primary's ports, so that worktree claims
and uses only the ports in its own worktree.toml. The primary checkout keeps its fixed
ports.

A linked worktree whose .odoo is a symlink to the primary checkout's .odoo uses that
one folder and the primary ports. Its PostgreSQL database name comes from the folder
name (ibcorr-ticket-00017 uses ibcorr_ticket_00017). It has no worktree.toml of its own.

Ports are never reserved: a worktree's ports are free as soon as its folder (with
its .odoo configuration) is gone and nothing listens on them.
"""

from __future__ import annotations

import argparse
import config
import contextlib
import fcntl
import glob
import os
import shlex
import socket
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_REGISTER = "~/Work/sys-admin/odoo/ports.toml"
MAX_PORT = 65535


class PortError(Exception):
    pass


@dataclass
class Pool:
    name: str
    main: int | None = None
    main_test: tuple[int, int] | None = None
    worktrees: tuple[int, int] | None = None
    worktree_tests: tuple[int, int] | None = None
    test_block: int = 100
    remove_hook: str = ""

    def http_ports(self) -> set[int]:
        ports = set()
        if self.main is not None:
            ports.add(self.main)
        if self.worktrees:
            ports.update(range(self.worktrees[0], self.worktrees[1] + 1))
        return ports

    def test_ports(self) -> set[int]:
        ports = set()
        for span in (self.main_test, self.worktree_tests):
            if span:
                ports.update(range(span[0], span[1] + 1))
        return ports

    def describe(self) -> str:
        parts = []
        parts.append(f"main {self.main if self.main is not None else 'unset'}")
        if self.worktrees:
            parts.append("worktrees %s-%s" % self.worktrees)
        if self.main_test:
            parts.append("main tests %s-%s" % self.main_test)
        if self.worktree_tests:
            parts.append("worktree tests %s-%s" % self.worktree_tests)
        return ", ".join(parts)


@dataclass
class Register:
    path: Path
    pools: dict[str, Pool]
    gevent_offset: int = 500
    public_offset: int = 10000
    work_root: Path = field(default_factory=lambda: Path("~/Work").expanduser())

    def pool(self, project: str) -> Pool:
        try:
            return self.pools[project]
        except KeyError:
            raise PortError(
                f"project '{project}' has no port pool in {self.path}. "
                "Add a [projects.%s] block before starting anything." % project
            ) from None

    def gevent_ports(self, pool: Pool) -> set[int]:
        return {port + self.gevent_offset for port in pool.http_ports()}


def _span(value, name: str, key: str) -> tuple[int, int] | None:
    if value is None:
        return None
    if (not isinstance(value, list) or len(value) != 2
            or not all(isinstance(item, int) for item in value) or value[0] > value[1]):
        raise PortError(f"projects.{name}.{key} must be [first, last]")
    if not 1 <= value[0] <= value[1] <= MAX_PORT:
        raise PortError(f"projects.{name}.{key} is outside 1-{MAX_PORT}")
    return (value[0], value[1])


def register_path(environ=None) -> tuple[Path, bool]:
    environ = os.environ if environ is None else environ
    explicit = environ.get("ODOO_PORTS_REGISTER")
    if explicit:
        return Path(explicit).expanduser(), True
    home = environ.get("HOME")
    default = DEFAULT_REGISTER.replace("~", home, 1) if home else DEFAULT_REGISTER
    return Path(default).expanduser(), False


def load_register(path: Path | None = None, *, required: bool = False, environ=None) -> Register | None:
    environ = os.environ if environ is None else environ
    if path is None:
        path, required = register_path(environ)
    if not path.is_file():
        if required:
            raise PortError(f"port register not found: {path}")
        return None
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as error:
        raise PortError(f"invalid TOML in {path}: {error}") from None
    if data.get("version") != 1:
        raise PortError(f"{path}: version must be 1")
    pools = {}
    for name, raw in (data.get("projects") or {}).items():
        if not isinstance(raw, dict):
            raise PortError(f"projects.{name} must be a table")
        main = raw.get("main")
        if main is not None and not isinstance(main, int):
            raise PortError(f"projects.{name}.main must be an integer")
        block = raw.get("test_block", 100)
        if not isinstance(block, int) or block < 2:
            raise PortError(f"projects.{name}.test_block must be an integer >= 2")
        pools[name] = Pool(
            name=name, main=main,
            main_test=_span(raw.get("main_test"), name, "main_test"),
            worktrees=_span(raw.get("worktrees"), name, "worktrees"),
            worktree_tests=_span(raw.get("worktree_tests"), name, "worktree_tests"),
            test_block=block,
            remove_hook=str(raw.get("remove_hook") or ""),
        )
    work_root = environ.get("ODOO_PORTS_WORK_ROOT") or data.get("work_root") or "~/Work"
    register = Register(
        path=path, pools=pools,
        gevent_offset=int(data.get("gevent_offset", 500)),
        public_offset=int(data.get("public_offset", 10000)),
        work_root=Path(work_root).expanduser(),
    )
    overlaps = register_overlaps(register)
    if overlaps:
        raise PortError(f"{path}: pools overlap: " + "; ".join(overlaps[:5]))
    return register


def register_overlaps(register: Register) -> list[str]:
    owner: dict[int, str] = {}
    found = []
    for pool in register.pools.values():
        claimed = (pool.http_ports() | pool.test_ports() | register.gevent_ports(pool)
                   | {port + register.public_offset for port in pool.http_ports()})
        clashes = {}
        for port in claimed:
            other = owner.get(port)
            if other and other != pool.name:
                clashes.setdefault(other, []).append(port)
            owner.setdefault(port, pool.name)
        for other, ports in clashes.items():
            found.append(f"{pool.name} and {other} share {min(ports)}-{max(ports)}")
    return found


# ---------------------------------------------------------------- claims

def _merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _load_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text()) if path.is_file() else {}
    except (tomllib.TOMLDecodeError, OSError):
        return {}


def checkout_ports(root: Path, gevent_offset: int = 500) -> tuple[str, set[int]]:
    """Project name and every port one checkout's .odoo configuration claims.

    A linked worktree claims only its own worktree.toml ports: its config.toml is a copy
    of the primary's, so anything else in it is not this worktree's to claim.
    """
    config = _merge(_load_toml(root / ".odoo" / "config.toml"), _load_toml(root / ".odoo" / "worktree.toml"))
    project = str((config.get("project") or {}).get("name") or root.name)
    if is_linked_worktree(root):
        values = _load_toml(root / ".odoo" / "worktree.toml").get("ports") or {}
    else:
        values = config.get("ports") or {}
    ports = set()
    http = values.get("http")
    if isinstance(http, int):
        ports.add(http)
        gevent = values.get("gevent")
        ports.add(gevent if isinstance(gevent, int) else http + gevent_offset)
    for key in ("test_http", "test_gevent"):
        if isinstance(values.get(key), int):
            ports.add(values[key])
    start, end = values.get("test_range_start"), values.get("test_range_end")
    if isinstance(start, int) and isinstance(end, int) and start <= end:
        ports.update(range(start, end + 1))
    return project, ports


def checkout_roots(work_root: Path, extra_roots=()) -> list[Path]:
    roots = {Path(p).parent.parent.resolve()
             for p in glob.glob(str(work_root / "*" / ".odoo" / "config.toml"))}
    roots.update(Path(r).resolve() for r in extra_roots)
    return sorted(roots)


def git_worktree_roots(root: Path) -> list[Path]:
    try:
        out = subprocess.run(["git", "-C", str(root), "worktree", "list", "--porcelain"],
                             capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return [Path(line[9:]) for line in out.splitlines() if line.startswith("worktree ")]


def claims(register: Register, extra_roots=()) -> dict[int, list[tuple[Path, str]]]:
    """Port -> [(checkout root, project)] for every checkout under work_root (plus extras)."""
    owners: dict[int, list[tuple[Path, str]]] = {}
    for root in checkout_roots(register.work_root, extra_roots):
        if not (root / ".odoo" / "config.toml").is_file():
            continue
        project, ports = checkout_ports(root, register.gevent_offset)
        for port in ports:
            owners.setdefault(port, []).append((root, project))
    return owners


def legitimate(register: Register, port: int, project: str) -> bool:
    """A claim counts against others only when the claimant's own pool allows it.

    A stale configuration outside its project's pool cannot start (check refuses it),
    so it does not block the project that owns the port; allocate still avoids it.
    """
    pool = register.pools.get(project)
    if pool is None:
        return True
    return (port in pool.http_ports() or port in pool.test_ports()
            or port in register.gevent_ports(pool))


def listening_ports() -> set[int] | None:
    """TCP ports in LISTEN state per `ss`; None when ss is unavailable."""
    try:
        out = subprocess.run(["ss", "-ltnH"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    ports = set()
    for line in out.splitlines():
        fields = line.split()
        if len(fields) >= 4:
            port = fields[3].rsplit(":", 1)[-1]
            if port.isdigit():
                ports.add(int(port))
    return ports


def _bind_free(port: int) -> bool:
    try:
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False


def make_listening_check(listening: set[int] | None = None):
    if listening is None:
        listening = listening_ports()
    if listening is None:
        return lambda port: not _bind_free(port)
    return lambda port: port in listening


# ---------------------------------------------------------------- policy

def worktree_slot(register: Register, pool: Pool, slot: int) -> dict[str, int]:
    http = pool.worktrees[0] + slot
    test_start = pool.worktree_tests[0] + slot * pool.test_block
    return {
        "http": http,
        "gevent": http + register.gevent_offset,
        "test_start": test_start,
        "test_end": test_start + pool.test_block - 1,
    }


def allocate(register: Register, project: str, root: Path | None = None,
             owners: dict[int, list[tuple[Path, str]]] | None = None,
             is_listening=None) -> dict[str, int]:
    pool = register.pool(project)
    if not pool.worktrees or not pool.worktree_tests:
        raise PortError(f"project '{project}' has no worktree pool in {register.path}")
    owners = claims(register) if owners is None else owners
    is_listening = make_listening_check() if is_listening is None else is_listening
    me = root.resolve() if root else None
    for slot in range(pool.worktrees[1] - pool.worktrees[0] + 1):
        candidate = worktree_slot(register, pool, slot)
        if candidate["test_end"] > pool.worktree_tests[1]:
            break
        ports = {candidate["http"], candidate["gevent"],
                 *range(candidate["test_start"], candidate["test_end"] + 1)}
        taken = any(any(owner != me for owner, _ in owners.get(port, ())) for port in ports)
        if not taken and not any(is_listening(port) for port in ports):
            return candidate
    raise PortError("no free worktree slot left in %s's pool (%s)" % (project, pool.describe()))


def check(register: Register, project: str, root: Path, http: int, gevent: int | None = None,
          test: tuple[int, int] | None = None,
          owners: dict[int, list[tuple[Path, str]]] | None = None) -> list[str]:
    """Problems with a checkout using these ports; empty when it may start."""
    pool = register.pool(project)
    problems = []
    if http not in pool.http_ports():
        problems.append(f"http port {http} is outside {project}'s pool ({pool.describe()})")
    if gevent is not None and gevent != http + register.gevent_offset:
        problems.append(f"gevent port {gevent} must be http + {register.gevent_offset} = "
                        f"{http + register.gevent_offset}")
    if test is not None:
        allowed = pool.test_ports()
        outside = [port for port in test if port not in allowed]
        if outside:
            problems.append("test ports %s-%s are outside %s's test pool (%s)"
                            % (test[0], test[1], project, pool.describe()))
    owners = claims(register, [root]) if owners is None else owners
    me = root.resolve()
    shared_primary = None
    if config.uses_shared_odoo(root):
        primary = primary_checkout(root)
        shared_primary = primary.resolve() if primary is not None else None
    mine = {http} | ({gevent} if gevent else set())
    if test is not None:
        mine |= set(range(test[0], test[1] + 1))
    for port in sorted(mine):
        others = [str(owner) for owner, other in owners.get(port, ())
                  if owner != me and owner.resolve() != shared_primary
                  and legitimate(register, port, other)]
        if others:
            problems.append(f"port {port} is also assigned to {', '.join(others)}")
    return problems


# ---------------------------------------------------------------- worktrees and assignment

LOCK_DEFAULT = "~/.cache/odoo-utils/ports.lock"


def git_dirs(root: Path) -> tuple[Path, Path] | None:
    """(git dir, common git dir) of a checkout, both absolute; None outside a repository."""
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--path-format=absolute",
                              "--git-dir", "--git-common-dir"],
                             capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    git_dir, common = out.split()
    return Path(git_dir).resolve(), Path(common).resolve()


def is_linked_worktree(root: Path) -> bool:
    """True for a linked worktree (git worktree add): its git dir differs from the common one."""
    dirs = git_dirs(root)
    return dirs is not None and dirs[0] != dirs[1]


def primary_checkout(root: Path) -> Path | None:
    dirs = git_dirs(root)
    return dirs[1].parent if dirs else None


def worktree_problems(root: Path, gevent_offset: int = 500) -> list[str]:
    """Why a linked worktree may not start Odoo; empty for the primary checkout or a valid worktree."""
    if not is_linked_worktree(root):
        return []
    if config.uses_shared_odoo(root):
        if config.shared_worktree_database(root):
            return []
        return [f"linked worktree {root} points .odoo at the primary checkout, but its folder "
                "name does not name a private database"]
    values = _load_toml(root / ".odoo" / "worktree.toml").get("ports") or {}
    if not isinstance(values.get("http"), int):
        return [f"linked worktree {root} has no ports of its own (.odoo/worktree.toml has no "
                "[ports] http); it must not use the primary checkout's ports"]
    primary = primary_checkout(root)
    if primary is None:
        return []
    _, mine = checkout_ports(root, gevent_offset)
    _, primary_ports = checkout_ports(primary, gevent_offset)
    shared = sorted(mine & primary_ports)
    if shared:
        return [f"ports {_ranges(shared)} of {root} belong to the primary checkout {primary}"]
    return []


def default_register(environ=None) -> Register:
    """Used when no register exists: nothing is enforced, but claims are still checked."""
    environ = os.environ if environ is None else environ
    work_root = Path(environ.get("ODOO_PORTS_WORK_ROOT") or "~/Work").expanduser()
    return Register(path=Path("(no register)"), pools={}, work_root=work_root)


def ports_lock_path(environ=None) -> Path:
    environ = os.environ if environ is None else environ
    return Path(environ.get("ODOO_PORTS_LOCK") or LOCK_DEFAULT).expanduser()


@contextlib.contextmanager
def ports_lock(environ=None):
    """Exclusive lock around every assignment, so two allocations never pick the same slot."""
    path = ports_lock_path(environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def worktree_text(database: str, ports: dict[str, int], data_dir: Path) -> str:
    # data_dir is written here because the committed config.toml carries the primary's path,
    # and the filestore must be the worktree's own folder.
    return (
        f'[odoo]\ndata_dir = "{data_dir}"\n\n'
        f'[database]\nname = "{database}"\n\n'
        f'[ports]\nhttp = {ports["http"]}\ngevent = {ports["gevent"]}\n'
        f'test_http = {ports["test_start"]}\ntest_gevent = {ports["test_start"] + 1}\n'
        f'test_range_start = {ports["test_start"]}\ntest_range_end = {ports["test_end"]}\n\n'
        f'[targets.local]\nurl = "http://127.0.0.1:{ports["http"]}"\ndatabase = "{database}"\n'
    )


def _atomic_write(path: Path, text: str) -> None:
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".worktree.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
        os.replace(temp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp)
        raise


def assign(register: Register | None, project: str, root: Path, database: str,
           http: int | None = None, test_start: int | None = None, environ=None) -> dict[str, int]:
    """Give a linked worktree its ports and write its worktree.toml, all under the port lock.

    With a register the ports come from the project's worktree pool (the first free slot, or
    the slot of --http). Without one, --http and --test-start are required and only the
    claims of other checkouts are checked.
    """
    if not database:
        raise PortError("a database name is required")
    if (root / ".odoo").is_symlink():
        raise PortError(
            f"{root} .odoo is a symlink to {(root / '.odoo').resolve()}. "
            "Refusing to write worktree.toml through it."
        )
    if not is_linked_worktree(root):
        raise PortError(f"{root} is the primary checkout; its ports are fixed in config.toml. "
                        "Only a linked worktree (git worktree add) gets an allocation")
    gevent_offset = register.gevent_offset if register else 500
    with ports_lock(environ):
        owners = claims(register or default_register(environ), [root, *git_worktree_roots(root)])
        if register is not None:
            if http is None:
                ports = allocate(register, project, root, owners=owners)
            else:
                ports = slot_for_http(register, project, http)
                if test_start is not None and test_start != ports["test_start"]:
                    raise PortError(f"port {http} uses test ports {ports['test_start']}-"
                                    f"{ports['test_end']} in the register, not {test_start}")
        else:
            if http is None or test_start is None:
                raise PortError("without a port register --http and --test-start are required")
            ports = {"http": http, "gevent": http + gevent_offset,
                     "test_start": test_start, "test_end": test_start + 101}
        me = root.resolve()
        wanted = {ports["http"], ports["gevent"], *range(ports["test_start"], ports["test_end"] + 1)}
        for port in sorted(wanted):
            others = [str(owner) for owner, _ in owners.get(port, ()) if owner != me]
            if others:
                raise PortError(f"port {port} is also assigned to {', '.join(others)}")
        path = root / ".odoo" / "worktree.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, worktree_text(database, ports, root / ".odoo" / "data"))
    return ports


# ---------------------------------------------------------------- CLI

def _ranges(ports) -> str:
    ports = sorted(set(ports))
    spans, start = [], None
    for index, port in enumerate(ports):
        if start is None:
            start = port
        if index + 1 == len(ports) or ports[index + 1] != port + 1:
            spans.append(str(start) if start == port else f"{start}-{port}")
            start = None
    return ", ".join(spans)


def _cmd_show(register: Register, _args) -> int:
    print(f"register: {register.path}")
    print(f"{'project':<10} {'main':<6} {'worktrees':<11} {'main tests':<12} {'worktree tests':<14} block")
    for pool in register.pools.values():
        fmt = lambda span: "%s-%s" % span if span else "-"
        print(f"{pool.name:<10} {pool.main if pool.main is not None else 'TBD':<6} "
              f"{fmt(pool.worktrees):<11} {fmt(pool.main_test):<12} {fmt(pool.worktree_tests):<14} "
              f"{pool.test_block}")
    print(f"gevent = http + {register.gevent_offset}; public = http + {register.public_offset}")
    owners = claims(register)
    shared: dict[tuple, list[int]] = {}
    for port in sorted(owners):
        entries = tuple(sorted(set(owners[port])))
        if len({root for root, _ in entries}) > 1:
            shared.setdefault(entries, []).append(port)
    for entries, ports in shared.items():
        print(f"CLASH {_ranges(ports)}: " + ", ".join(f"{root} ({project})" for root, project in entries))
    outside: dict[tuple[Path, str], list[int]] = {}
    for port in sorted(owners):
        for root, project in owners[port]:
            if project in register.pools and not legitimate(register, port, project):
                outside.setdefault((root, project), []).append(port)
            elif project not in register.pools:
                outside.setdefault((root, project + ", no pool"), []).append(port)
    for (root, project), ports in outside.items():
        print(f"OUTSIDE POOL {root} ({project}): {_ranges(ports)}")
    for root in checkout_roots(register.work_root):
        for problem in worktree_problems(root, register.gevent_offset):
            print(f"NO OWN PORTS {problem}")
    return 0


def _cmd_allocate(register: Register, args) -> int:
    root = Path(args.root) if args.root else None
    extra = git_worktree_roots(root) if root else []
    _print_shell(allocate(register, args.project, root, owners=claims(register, extra)))
    return 0


def _cmd_assign(register: Register | None, args) -> int:
    ports = assign(register, args.project, Path(args.root), args.db, args.http, args.test_start)
    _print_shell(ports)
    return 0


def _cmd_guard(args) -> int:
    problems = worktree_problems(Path(args.root))
    for problem in problems:
        print(f"Error: {problem}.", file=sys.stderr)
    if problems:
        print("Fix: run 'odoo-init-env --worktree --db NAME' in this worktree to allocate its "
              "own ports from the project's pool.", file=sys.stderr)
        return 1
    return 0


def _cmd_check(register: Register, args) -> int:
    root = Path(args.root)
    test = tuple(args.test) if args.test else None
    problems = check(register, args.project, root, args.http, args.gevent, test,
                     owners=claims(register, [root, *git_worktree_roots(root)]))
    for problem in problems:
        print(f"Error: {problem}.", file=sys.stderr)
    if problems:
        print(f"Port pools are defined in {register.path}; use a port from this "
              "project's pool (odoo-utils ports.py allocate PROJECT).", file=sys.stderr)
        return 1
    return 0


def slot_for_http(register: Register, project: str, http: int) -> dict[str, int]:
    """The canonical worktree slot of an http port in the project's worktree pool."""
    pool = register.pool(project)
    if not pool.worktrees or not pool.worktree_tests or not (
            pool.worktrees[0] <= http <= pool.worktrees[1]):
        raise PortError(f"http port {http} is outside {project}'s worktree pool ({pool.describe()})")
    ports = worktree_slot(register, pool, http - pool.worktrees[0])
    if ports["test_end"] > pool.worktree_tests[1]:
        raise PortError(f"http port {http} has no test block inside {project}'s worktree test pool")
    return ports


def _print_shell(ports: dict[str, int]) -> None:
    for key, value in ports.items():
        print(f"{key}={shlex.quote(str(value))}")


def _cmd_slot(register: Register, args) -> int:
    _print_shell(slot_for_http(register, args.project, args.http))
    return 0


def _cmd_active(register: Register, _args) -> int:
    print(register.path)
    return 0


def _cmd_hook(register: Register, args) -> int:
    hook = register.pools.get(args.project, Pool(args.project)).remove_hook
    if hook:
        print(hook)
    return 0


def _cmd_gevent(register: Register, args) -> int:
    register.pool(args.project)
    print(args.http + register.gevent_offset)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--register", help="register path (default $ODOO_PORTS_REGISTER or %s)" % DEFAULT_REGISTER)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show")
    p = sub.add_parser("allocate")
    p.add_argument("project")
    p.add_argument("--root")
    p = sub.add_parser("assign")
    p.add_argument("project")
    p.add_argument("--root", required=True)
    p.add_argument("--db", required=True)
    p.add_argument("--http", type=int)
    p.add_argument("--test-start", type=int)
    p = sub.add_parser("guard")
    p.add_argument("--root", required=True)
    p = sub.add_parser("check")
    p.add_argument("project")
    p.add_argument("--root", required=True)
    p.add_argument("--http", type=int, required=True)
    p.add_argument("--gevent", type=int)
    p.add_argument("--test", type=int, nargs=2, metavar=("START", "END"))
    p = sub.add_parser("slot")
    p.add_argument("project")
    p.add_argument("--http", type=int, required=True)
    sub.add_parser("active")
    p = sub.add_parser("hook")
    p.add_argument("project")
    p = sub.add_parser("gevent")
    p.add_argument("project")
    p.add_argument("--http", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "guard":
            return _cmd_guard(args)
        if args.register:
            register = load_register(Path(args.register).expanduser(), required=True)
        else:
            register = load_register()
        if args.command == "assign":
            return _cmd_assign(register, args)
        if register is None:
            # No register: nothing to enforce. allocate/show still need one.
            if args.command in {"check", "gevent", "hook"}:
                return 0
            if args.command == "active":
                return 3
            raise PortError("no port register (set ODOO_PORTS_REGISTER or create %s)" % DEFAULT_REGISTER)
        return {"show": _cmd_show, "allocate": _cmd_allocate,
                "check": _cmd_check, "gevent": _cmd_gevent,
                "slot": _cmd_slot, "active": _cmd_active, "hook": _cmd_hook}[args.command](register, args)
    except PortError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
