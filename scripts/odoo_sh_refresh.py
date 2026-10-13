#!/usr/bin/env python3
"""Refresh a local Odoo database from the newest existing Odoo.sh daily backup.

It does three things and no other database work:
  1. fetch the newest daily backup over SSH and write its SQL to the project's .odoo/dump.sql
     (the filestore too, on its days or with --filestore);
  2. call the project's own `odoo-fresh` (drop, create, restore from .odoo/dump.sql);
  3. neutralise: the stock neutralize.sql of every installed module (what `odoo-bin neutralize`
     runs), then the project SQL, whose checks must pass.

Generic: every host, path and project detail comes from the TOML file given with --config.
The run never triggers a backup on Odoo.sh. It stops the checkout's running Odoo before
odoo-fresh (odoo-fresh cannot drop a database that is in use) and leaves it stopped, unless
--restart is given.

    [source]
    ssh = "user@project.odoo.com"              # SSH target of the Odoo.sh project
    key = "~/.ssh/id_ed25519"                  # identity for it (IdentitiesOnly is set)
    dump = "/home/odoo/backup.daily/<name>_daily.sql.gz"
    filestore = "/home/odoo/backup.daily/<name>_daily/home/odoo/data/filestore/<name>"

    [target]
    database = "ropeworx"                      # must be database.name in the checkout's .odoo/config.toml
    checkout = "~/Work/ropeworx"               # Odoo checkout with .odoo/
    conf = ".odoo/odoo.conf"                   # relative to checkout; finds the running Odoo and the addons path
    data_dir = "~/Work/ropeworx/.odoo/data"    # filestore lives in <data_dir>/filestore/<db>
    session = "ropeworx-main"                  # tmux session of the live Odoo, closed with it (may not exist)
    lock = "~/.cache/ropeworx-db-refresh.lock"
    state_dir = "~/.local/state/odoo-refresh/ropeworx"
    data_source = ".odoo/data-source"          # relative to checkout; first line is read by ibcorr-ports
    after = []                                 # commands run in the checkout after a good run

    [run]
    fresh = "~/.local/share/odoo/bin/odoo-fresh"   # the global odoo-fresh; required
    odoo_run = "~/.local/share/odoo/bin/odoo-run"  # used by --restart
    filestore_days = ["Sun"]                   # copy the filestore on these days (SAST)
    min_free_gb = 10
    min_backup_age_min = 20                    # refuse a backup that is still being written
    allowed_restore_errors = 0                 # psql ERROR lines odoo-fresh may print
    neutralize_sql = "~/Work/sys-admin/bin/ropeworx-neutralize.sql"

Steps: lock -> preflight -> download (dump.sql) -> stop Odoo -> filestore -> odoo-fresh
-> neutralise -> data-source stamp -> after-hooks [-> restart Odoo].

odoo-fresh replaces the database in place; there is no copy to fall back to. A run fails before
odoo-fresh if anything other than the stopped Odoo is still connected to the database.
"""

import argparse
import configparser
import datetime as dt
import fcntl
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path

SAST = dt.timezone(dt.timedelta(hours=2))
SSH_OPTIONS = ["-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=30", "-o", "LogLevel=ERROR"]
CARRIED = ("restored_backup_utc", "filestore_copied")


class Failed(Exception):
    def __init__(self, step, message):
        super().__init__(message)
        self.step = step


class Skip(Exception):
    def __init__(self, result, message):
        super().__init__(message)
        self.result = result


def now():
    return dt.datetime.now(dt.timezone.utc)


def stamp(moment=None):
    moment = moment or now()
    return "%s UTC (%s SAST)" % (moment.strftime("%Y-%m-%d %H:%M:%S"),
                                 moment.astimezone(SAST).strftime("%H:%M:%S"))


def log(message):
    print("%s  %s" % (stamp(), message), flush=True)


def path(value):
    return Path(os.path.expanduser(value))


def run(command, step, cwd=None, env=None, log_file=None, shell=False):
    """Run a command and return its output. Raises Failed, with the output tail, on a non-zero exit."""
    handle = open(log_file, "w") if log_file else None
    try:
        done = subprocess.run(command, cwd=cwd, env=env, shell=shell, text=True,
                              executable="/bin/bash" if shell else None,
                              stdout=handle or subprocess.PIPE,
                              stderr=subprocess.STDOUT if handle else subprocess.PIPE)
    finally:
        if handle:
            handle.close()
    output = Path(log_file).read_text(errors="replace") if log_file else done.stdout + done.stderr
    if done.returncode:
        shown = command if isinstance(command, str) else " ".join(map(str, command[:3])) + " ..."
        raise Failed(step, "%s exited %d\n%s" % (shown, done.returncode, output.strip()[-800:]))
    return output


class Refresh:
    def __init__(self, config, args):
        self.args = args
        src, tgt, rules = config["source"], config["target"], config["run"]
        if "fresh" not in rules:
            raise SystemExit("config has no [run] fresh: this version only restores through odoo-fresh; "
                             "set fresh = \"~/.local/share/odoo/bin/odoo-fresh\" after checking the project fits")
        self.ssh_target = src["ssh"]
        self.key = path(src["key"])
        self.dump_remote = src["dump"]
        self.filestore_remote = src["filestore"]
        self.db = tgt["database"]
        self.checkout = path(tgt["checkout"])
        self.conf = self.checkout / tgt["conf"]
        self.data_dir = path(tgt["data_dir"])
        self.session = tgt["session"]
        self.lock_file = path(tgt["lock"])
        self.state = path(tgt["state_dir"])
        self.data_source = self.checkout / tgt["data_source"]
        self.after = tgt.get("after", [])
        self.fresh = path(rules["fresh"])
        self.odoo_run = path(rules.get("odoo_run", "~/.local/share/odoo/bin/odoo-run"))
        self.days = rules["filestore_days"]
        self.min_free = rules["min_free_gb"] * 1024 ** 3
        self.min_age = dt.timedelta(minutes=rules["min_backup_age_min"])
        self.allowed_errors = rules["allowed_restore_errors"]
        self.neutralize_sql = path(rules["neutralize_sql"])
        self.status_file = self.state / "status.json"
        self.history = self.state / "history.log"
        self.gz = self.state / "prod.sql.gz"
        self.dump = self.checkout / ".odoo" / "dump.sql"
        self.started = now()
        self.warnings = []
        self.was_running = False
        self.previous = self.load_previous()
        # Facts about the live database survive a failed run; the rest describes this run only.
        self.status = {k: self.previous[k] for k in CARRIED if k in self.previous}
        self.status.update(result="running", step="start", started=stamp(self.started))

    # ---- status ------------------------------------------------------------------------

    def load_previous(self):
        try:
            return json.loads(self.status_file.read_text())
        except (OSError, ValueError):
            return {}

    def save_status(self):
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.status.update(duration_s=int((now() - self.started).total_seconds()),
                           finished=stamp(), warnings=self.warnings)
        tmp = self.status_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.status, indent=2) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.status_file)

    def step(self, name):
        self.status.update(step=name)
        self.save_status()

    def finish(self):
        line = "%s  %-22s %-14s backup=%s  %s" % (
            stamp(self.started), self.status["result"], self.status.get("step", ""),
            self.status.get("backup_utc", "-"), str(self.status.get("message", ""))[:200].replace("\n", " "))
        with open(self.history, "a") as handle:
            handle.write(line + "\n")
        self.save_status()

    # ---- remote and database helpers ---------------------------------------------------

    def ssh(self, command, step):
        return run(["ssh", *SSH_OPTIONS, "-i", str(self.key), self.ssh_target, command], step).strip()

    def rsync(self, source, target, step, extra=()):
        transport = "ssh %s -i %s" % (" ".join(SSH_OPTIONS), self.key)
        return run(["rsync", "-a", *extra, "-e", transport, source, target], step)

    def psql(self, sql, database="postgres", step="database"):
        return run(["psql", "-X", "-q", "-h", "localhost", "-U", "odoo", "-d", database,
                    "-v", "ON_ERROR_STOP=1", "-Atc", sql], step).strip()

    def database_oid(self):
        return self.psql("select oid from pg_database where datname = '%s'" % self.db)

    def connections(self):
        return int(self.psql("select count(*) from pg_stat_activity where datname = '%s'" % self.db))

    def odoo_running(self):
        return subprocess.run(["pgrep", "-f", "[o]doo-bin -c %s" % self.conf],
                              stdout=subprocess.DEVNULL).returncode == 0

    def stop_odoo(self):
        """Close the live Odoo of this checkout (its tmux session, then any process left)."""
        subprocess.run(["tmux", "kill-session", "-t", self.session],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-f", "[o]doo-bin -c %s" % self.conf])
        for _ in range(30):
            if not self.odoo_running():
                return
            time.sleep(1)
        raise Failed("stop", "Odoo for %s did not stop" % self.checkout)

    def remote_backup(self):
        reply = self.ssh("stat -c '%%Y %%s' %s" % shlex.quote(self.dump_remote), "preflight").splitlines()[-1]
        mtime, size = reply.split()
        return dt.datetime.fromtimestamp(int(mtime), dt.timezone.utc), int(size)

    def addons_paths(self):
        """The conf's addons_path plus Odoo's own odoo/odoo/addons (base, web), which Odoo adds itself."""
        parser = configparser.ConfigParser()
        parser.read(self.conf)
        paths = [Path(p.strip()) for p in parser.get("options", "addons_path").split(",") if p.strip()]
        core = [p.parent / "odoo" / "addons" for p in paths if (p.parent / "odoo" / "addons" / "base").is_dir()]
        return core[:1] + paths

    # ---- steps -------------------------------------------------------------------------

    def preflight(self):
        self.step("preflight")
        if not self.fresh.is_file():
            raise Failed("preflight", "odoo-fresh not found: %s" % self.fresh)
        backup, size = self.remote_backup()
        age = now() - backup
        if age < self.min_age:
            raise Failed("preflight", "newest backup is %s old; still being written" % age)
        free = shutil.disk_usage(self.data_dir).free
        if free < self.min_free:
            raise Failed("preflight", "only %.1f GB free" % (free / 1024 ** 3))
        self.backup_size = size
        self.status.update(backup_utc=backup.strftime("%Y-%m-%d %H:%M UTC"), backup_size=size)
        if self.status["backup_utc"] == self.status.get("restored_backup_utc") and not self.args.force:
            raise Skip("skipped:no-new-backup", "backup %s is already restored" % self.status["backup_utc"])
        log("backup: %s (%.0f MB)" % (self.status["backup_utc"], size / 1024 ** 2))
        log("live %s: %s connection(s); Odoo %s" % (
            self.db, self.connections(), "running" if self.odoo_running() else "not running"))

    def download(self):
        """Fetch the gzipped dump into state_dir, check it, and unpack it to .odoo/dump.sql (mode 600)."""
        self.step("download")
        part = self.state / "prod.sql.gz.part"
        self.rsync("%s:%s" % (self.ssh_target, self.dump_remote), str(part), "download", extra=["--partial"])
        if part.stat().st_size != self.backup_size:
            raise Failed("download", "size %d, expected %d" % (part.stat().st_size, self.backup_size))
        run(["gzip", "-t", str(part)], "download")
        os.chmod(part, 0o600)
        os.replace(part, self.gz)
        sql_part = self.dump.with_suffix(".sql.part")
        with open(sql_part, "wb") as handle:
            os.chmod(sql_part, 0o600)
            done = subprocess.run(["gunzip", "-c", str(self.gz)], stdout=handle)
        if done.returncode:
            sql_part.unlink(missing_ok=True)
            raise Failed("download", "gunzip exited %d" % done.returncode)
        os.replace(sql_part, self.dump)
        log("dump written to %s (%.0f MB)" % (self.dump, self.dump.stat().st_size / 1024 ** 2))

    def stop(self):
        self.step("stop")
        if self.odoo_running():
            self.was_running = True
            self.stop_odoo()
            self.status.update(stopped_odoo=True)
            log("stopped the running Odoo of %s" % self.checkout.name)
        left = self.connections()
        if left:
            raise Failed("stop", "%d connection(s) to %s remain; odoo-fresh would not drop it" % (left, self.db))

    def filestore(self):
        self.step("filestore")
        today = dt.datetime.now(SAST)
        if not (self.args.filestore or today.strftime("%a") in self.days):
            log("filestore kept (not a filestore day)")
            return
        target = self.data_dir / "filestore" / self.db
        target.mkdir(parents=True, exist_ok=True)
        self.rsync("%s:%s/" % (self.ssh_target, self.filestore_remote), "%s/" % target, "filestore",
                   extra=["--delete"])
        self.status["filestore_copied"] = today.strftime("%Y-%m-%d")
        log("filestore copied from Odoo.sh")

    def fresh_restore(self):
        """odoo-fresh drops, creates and restores the database from .odoo/dump.sql. Its psql restore does
        not stop on errors, so the result is checked here: a new database, no unexpected errors.
        TERM must name a real terminal: odoo-fresh runs `clear` under `set -e` (from common.sh)."""
        self.step("odoo-fresh")
        before = self.database_oid()
        log_file = self.state / "odoo-fresh.log"
        run([str(self.fresh)], "odoo-fresh", cwd=self.checkout, env=dict(os.environ, TERM="xterm"),
            log_file=log_file)
        after = self.database_oid()
        if not after or after == before:
            raise Failed("odoo-fresh", "%s was not recreated; see %s" % (self.db, log_file))
        errors = [line for line in log_file.read_text(errors="replace").splitlines() if "ERROR:" in line]
        self.status.update(restore_errors=len(errors))
        log("odoo-fresh restored %s with %d error line(s)" % (self.db, len(errors)))
        return errors

    def neutralize(self):
        self.step("neutralize")
        installed = self.psql("select name from ir_module_module where state = 'installed'", self.db,
                              "neutralize").split()
        files = []
        for module in installed:
            for base in self.addons_paths():
                candidate = base / module / "data" / "neutralize.sql"
                if candidate.is_file():
                    files.append(candidate)
                    break
        stock = ["psql", "-X", "-q", "-1", "-h", "localhost", "-U", "odoo", "-d", self.db, "-v", "ON_ERROR_STOP=1"]
        for candidate in files:
            stock += ["-f", str(candidate)]
        stock += ["-c", "INSERT INTO ir_config_parameter (key, value, create_date) "
                        "VALUES ('database.is_neutralized', 'True', now()) "
                        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"]
        run(stock, "neutralize", log_file=self.state / "neutralize-stock.log")
        log("stock neutralise SQL of %d installed module(s) applied" % len(files))
        run(["psql", "-X", "-q", "-h", "localhost", "-U", "odoo", "-d", self.db, "-v", "ON_ERROR_STOP=1",
             "-f", str(self.neutralize_sql)], "neutralize", log_file=self.state / "neutralize-sql.log")
        log("neutralised and checked (%s)" % self.neutralize_sql.name)

    def stamp_source(self):
        self.step("stamp")
        copied = self.status.get("filestore_copied", "unknown")
        self.status.update(restored_backup_utc=self.status["backup_utc"])
        self.data_source.write_text(
            "production backup %s (Odoo.sh daily), restored %s\nfilestore: copied %s\n" % (
                self.status["backup_utc"], stamp(), copied))

    def after_hooks(self):
        self.step("after")
        for command in self.after:
            try:
                run(["bash", "-lc", command], "after", cwd=self.checkout)
                log("after-hook ok: %s" % command)
            except Failed as exc:
                self.warnings.append("after-hook %s: %s" % (command, exc))
                log("after-hook failed: %s" % command)

    def restart(self):
        """--restart: start Odoo again with odoo-run --log, detached, if this run stopped it."""
        if not (self.args.restart and self.was_running):
            return
        subprocess.Popen([str(self.odoo_run), "--log"], cwd=self.checkout, start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            if self.odoo_running():
                self.status.update(restarted_odoo=True)
                log("Odoo started again (odoo-run --log)")
                return
            time.sleep(1)
        self.warnings.append("Odoo did not come back after --restart")

    # ---- driver ------------------------------------------------------------------------

    def execute(self):
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock = open(self.lock_file, "a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.status.update(result="skipped:locked", message="another refresh or clone holds the lock")
            lock.close()
            self.finish()
            return
        try:
            self.preflight()
            if self.args.check:
                self.status.update(result="checked", message="preflight only; nothing changed")
                return
            self.download()
            self.stop()
            self.filestore()
            errors = self.fresh_restore()
            # The database is replaced now: neutralise it before judging the restore.
            self.neutralize()
            if len(errors) > self.allowed_errors:
                raise Failed("odoo-fresh", "%d restore error line(s) (allowed %d); first: %s" % (
                    len(errors), self.allowed_errors, errors[:3]))
            self.stamp_source()
            self.after_hooks()
            self.status.update(result="ok", message="%s now holds backup %s" % (self.db, self.status["backup_utc"]))
        except Skip as exc:
            self.status.update(result=exc.result, message=str(exc))
        except Failed as exc:
            self.status.update(result="failed", step=exc.step, message=str(exc))
            log("FAILED at %s: %s" % (exc.step, exc))
        except Exception as exc:  # unexpected: still record it, never leave the status at "running"
            self.status.update(result="failed", message="%s: %s" % (type(exc).__name__, exc))
            log("FAILED unexpectedly at %s: %s" % (self.status.get("step"), exc))
            raise
        finally:
            try:
                self.restart()
            finally:
                lock.close()
                self.finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True, help="TOML file with the source, target and run settings")
    parser.add_argument("--filestore", action="store_true", help="copy the filestore tonight, not only on its days")
    parser.add_argument("--force", action="store_true", help="restore even if this backup is already restored")
    parser.add_argument("--check", action="store_true",
                        help="preflight only: read the backup, lock and disk; change nothing")
    parser.add_argument("--restart", action="store_true",
                        help="start the checkout's Odoo again (odoo-run --log) if this run stopped it")
    args = parser.parse_args()
    refresh = Refresh(tomllib.loads(path(args.config).read_text()), args)
    refresh.execute()
    print(json.dumps({k: refresh.status.get(k) for k in ("result", "step", "message")}, indent=2))
    sys.exit(1 if refresh.status["result"] == "failed" else 0)


if __name__ == "__main__":
    main()
