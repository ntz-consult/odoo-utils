#!/usr/bin/env python3
"""Refresh a local Odoo database from the newest existing Odoo.sh daily backup.

Generic: every host, path and project detail comes from the TOML file given with --config.
The run never triggers a backup on Odoo.sh and never starts an Odoo server.

    [source]
    ssh = "user@project.odoo.com"              # SSH target of the Odoo.sh project
    key = "~/.ssh/id_ed25519"                  # identity for it (IdentitiesOnly is set)
    dump = "/home/odoo/backup.daily/<name>_daily.sql.gz"
    filestore = "/home/odoo/backup.daily/<name>_daily/home/odoo/data/filestore/<name>"

    [target]
    database = "ibcorr"                        # the live database; replaced at the swap
    checkout = "~/Work/ibcorr"                 # Odoo checkout with .odoo/
    odoo_bin = "~/Odoo/V19/odoo/odoo-bin"
    conf = ".odoo/odoo.conf"                   # relative to checkout
    venv = ".venv"                             # relative to checkout; its python runs odoo-bin
    data_dir = "~/Work/ibcorr/.odoo/data"      # filestore lives in <data_dir>/filestore/<db>
    session = "odoo-ibcorr"                    # tmux session of the live Odoo; stopped at the swap
    lock = "~/.cache/ibcorr-db-refresh.lock"   # shared with the worktree refresh
    state_dir = "~/.local/state/odoo-refresh/ibcorr"
    data_source = ".odoo/data-source"          # relative to checkout; first line is read by ibcorr-ports
    after = ["ibcorr-local-login", "ibcorr-test-user"]   # run in the checkout after the swap

    [run]
    filestore_days = ["Sun"]                   # copy the filestore on these days (SAST)
    min_free_gb = 10
    min_backup_age_min = 20                    # refuse a backup that is still being written
    allowed_restore_errors = 1                 # restore errors that are known and accepted
    min_ratio = 0.9                            # new row counts must be this share of the old
    count_tables = ["account_move", "sale_order", "res_users|login not in ('odoo', 'admin')"]
    neutralize_sql = "~/Work/sys-admin/bin/ibcorr-neutralize.sql"

Steps: lock -> preflight -> download the dump -> filestore -> restore into <database>_new
-> update all modules -> neutralise (odoo-bin, then the project SQL with its checks)
-> row counts -> swap -> data-source stamp -> after-hooks.

Any failure before the swap drops <database>_new and its filestore; <database> stays as it was.
The swap is the only step that changes <database>. A failed swap is rolled back. The previous
copy is dropped right after a good swap. The latest dump is kept (mode 600) in state_dir.
"""

import argparse
import datetime as dt
import fcntl
import json
import os
import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

SAST = dt.timezone(dt.timedelta(hours=2))
SSH_OPTIONS = ["-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=30", "-o", "LogLevel=ERROR"]
CARRIED = ("restored_backup_utc", "filestore_copied")
ODOO_RUNNING = "skipped:odoo-running"


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
        self.ssh_target = src["ssh"]
        self.key = path(src["key"])
        self.dump_remote = src["dump"]
        self.filestore_remote = src["filestore"]
        self.db = tgt["database"]
        self.new = self.db + "_new"
        self.old = self.db + "_old"
        self.checkout = path(tgt["checkout"])
        self.odoo_bin = path(tgt["odoo_bin"])
        self.conf = self.checkout / tgt["conf"]
        self.python = self.checkout / tgt["venv"] / "bin" / "python"
        self.data_dir = path(tgt["data_dir"])
        self.session = tgt["session"]
        self.lock_file = path(tgt["lock"])
        self.state = path(tgt["state_dir"])
        self.data_source = self.checkout / tgt["data_source"]
        self.after = tgt.get("after", [])
        self.days = rules["filestore_days"]
        self.min_free = rules["min_free_gb"] * 1024 ** 3
        self.min_age = dt.timedelta(minutes=rules["min_backup_age_min"])
        self.allowed_errors = rules["allowed_restore_errors"]
        self.min_ratio = rules["min_ratio"]
        self.count_tables = rules["count_tables"]
        self.neutralize_sql = path(rules["neutralize_sql"])
        self.status_file = self.state / "status.json"
        self.history = self.state / "history.log"
        self.dump = self.state / "prod.sql.gz"
        self.started = now()
        self.warnings = []
        self.swapped = False
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

    def database_exists(self, name):
        return self.psql("select 1 from pg_database where datname = '%s'" % name) == "1"

    def terminate(self, name):
        self.psql("select pg_terminate_backend(pid) from pg_stat_activity "
                  "where datname = '%s' and pid <> pg_backend_pid()" % name)

    def odoo_running(self):
        return subprocess.run(["pgrep", "-f", "[o]doo-bin -c %s" % self.conf],
                              stdout=subprocess.DEVNULL).returncode == 0

    def remote_backup(self):
        reply = self.ssh("stat -c '%%Y %%s' %s" % shlex.quote(self.dump_remote), "preflight").splitlines()[-1]
        mtime, size = reply.split()
        return dt.datetime.fromtimestamp(int(mtime), dt.timezone.utc), int(size)

    def filestore_path(self, name):
        return self.data_dir / "filestore" / name

    def drop_new(self):
        """Remove a leftover or failed <database>_new and its filestore. Never touches <database>."""
        if self.database_exists(self.new):
            self.terminate(self.new)
            self.psql('drop database "%s"' % self.new)
        shutil.rmtree(self.filestore_path(self.new), ignore_errors=True)

    # ---- steps -------------------------------------------------------------------------

    def preflight(self):
        self.step("preflight")
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
            self.db, self.psql("select count(*) from pg_stat_activity where datname = '%s'" % self.db),
            "running" if self.odoo_running() else "not running"))

    def download(self):
        self.step("download")
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        part = self.state / "prod.sql.gz.part"
        self.rsync("%s:%s" % (self.ssh_target, self.dump_remote), str(part), "download", extra=["--partial"])
        if part.stat().st_size != self.backup_size:
            raise Failed("download", "size %d, expected %d" % (part.stat().st_size, self.backup_size))
        run(["gzip", "-t", str(part)], "download")
        os.chmod(part, 0o600)
        os.replace(part, self.dump)
        log("dump downloaded and checked: %s" % self.dump.name)

    def filestore(self):
        self.step("filestore")
        target = self.filestore_path(self.new)
        target.parent.mkdir(parents=True, exist_ok=True)
        today = dt.datetime.now(SAST)
        if self.args.filestore or today.strftime("%a") in self.days:
            target.mkdir()
            self.rsync("%s:%s/" % (self.ssh_target, self.filestore_remote), "%s/" % target, "filestore",
                       extra=["--delete"])
            self.status["filestore_copied"] = today.strftime("%Y-%m-%d")
            log("filestore copied from Odoo.sh")
        else:
            source = self.filestore_path(self.db)
            if not source.is_dir():
                raise Failed("filestore", "no filestore to copy from: %s" % source)
            run(["cp", "-al", str(source), str(target)], "filestore")
            log("filestore hard-linked from the current copy (not a filestore day)")

    def restore(self):
        self.step("restore")
        self.psql('create database "%s" owner odoo' % self.new)
        run(["sudo", "-n", "-u", "postgres", "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1",
             "-d", self.new, "-c", "create extension if not exists vector"], "restore")
        log_file = self.state / "restore.log"
        command = "set -o pipefail; gunzip -c %s | psql -X -q -h localhost -U odoo -d %s -v ON_ERROR_STOP=0" % (
            shlex.quote(str(self.dump)), shlex.quote(self.new))
        run(command, "restore", shell=True, log_file=log_file)
        errors = [line for line in log_file.read_text(errors="replace").splitlines() if line.startswith("ERROR:")]
        self.status.update(restore_errors=len(errors))
        if len(errors) > self.allowed_errors:
            raise Failed("restore", "%d restore errors (allowed %d); first: %s" % (
                len(errors), self.allowed_errors, errors[:3]))
        log("restored into %s with %d accepted error(s)" % (self.new, len(errors)))

    def odoo_command(self, *args):
        return [str(self.python), str(self.odoo_bin), *args]

    def update(self):
        self.step("update")
        env = dict(os.environ, PATH="%s:%s" % (self.python.parent, os.environ["PATH"]))
        run(self.odoo_command("-c", str(self.conf), "-d", self.new, "-u", "all", "--stop-after-init",
                              "--no-http", "--max-cron-threads=0"),
            "update", cwd=self.checkout, env=env, log_file=self.state / "update.log")
        log("modules updated to the checkout's code")

    def neutralize(self):
        self.step("neutralize")
        run(self.odoo_command("neutralize", "-c", str(self.conf), "-d", self.new), "neutralize",
            cwd=self.checkout, log_file=self.state / "neutralize.log")
        run(["psql", "-X", "-q", "-h", "localhost", "-U", "odoo", "-d", self.new, "-v", "ON_ERROR_STOP=1",
             "-f", str(self.neutralize_sql)], "neutralize", log_file=self.state / "neutralize-sql.log")
        log("neutralised and checked (%s)" % self.neutralize_sql.name)

    def counts(self, database):
        """Row counts per table. An entry 'table|where' counts only the rows matching the condition."""
        selects = []
        for entry in self.count_tables:
            table, _, condition = entry.partition("|")
            selects.append("select '%s', count(*) from \"%s\"%s" % (
                table, table, " where " + condition if condition else ""))
        rows = self.psql(" union all ".join(selects), database, "counts")
        return {name: int(value) for name, value in (line.split("|") for line in rows.splitlines())}

    def sanity(self):
        self.step("sanity")
        old, new = self.counts(self.db), self.counts(self.new)
        tables = [entry.partition("|")[0] for entry in self.count_tables]
        self.status.update(row_counts={t: [old[t], new[t]] for t in old})
        for table in old:
            if old[table] and new[table] < self.min_ratio * old[table]:
                raise Failed("sanity", "%s: %d rows in the new copy, %d in %s" % (
                    table, new[table], old[table], self.db))
        log("row counts ok: %s" % ", ".join("%s %d" % (t, new[t]) for t in tables))

    def swap(self):
        self.step("swap")
        if self.odoo_running():
            raise Skip(ODOO_RUNNING, "Odoo for %s is running; it is not stopped, nothing was swapped" % self.checkout)
        self.terminate(self.db)
        self.terminate(self.new)
        live, spare, fresh = (self.filestore_path(n) for n in (self.db, self.old, self.new))
        done = []
        try:
            self.psql('alter database "%s" rename to "%s"' % (self.db, self.old))
            done.append("db-old")
            self.psql('alter database "%s" rename to "%s"' % (self.new, self.db))
            done.append("db-new")
            if live.is_dir():
                os.rename(live, spare)
                done.append("fs-old")
            os.rename(fresh, live)
            done.append("fs-new")
        except (Failed, OSError) as exc:
            self.revert_swap(done, live, spare, fresh)
            raise Failed("swap", "swap reverted: %s" % exc)
        self.swapped = True
        log("swapped: %s is the new copy" % self.db)

    def revert_swap(self, done, live, spare, fresh):
        steps = {
            "fs-new": lambda: os.rename(live, fresh),
            "fs-old": lambda: os.rename(spare, live),
            "db-new": lambda: self.psql('alter database "%s" rename to "%s"' % (self.db, self.new)),
            "db-old": lambda: self.psql('alter database "%s" rename to "%s"' % (self.old, self.db)),
        }
        for name in reversed(done):
            try:
                steps[name]()
            except Exception as exc:  # report every part that could not be put back
                self.warnings.append("swap revert %s failed: %s" % (name, exc))

    def cleanup_old(self):
        """Drop the previous copy after a good swap. A failure here is a warning, not a failed run."""
        try:
            self.terminate(self.old)
            self.psql('drop database "%s"' % self.old)
            shutil.rmtree(self.filestore_path(self.old), ignore_errors=True)
            log("dropped the previous copy %s" % self.old)
        except Failed as exc:
            self.warnings.append("previous copy %s not dropped: %s" % (self.old, exc))

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
            if self.odoo_running() and not self.args.rehearse:
                raise Skip(ODOO_RUNNING, "Odoo for %s is running; not touched, nothing changed" % self.checkout)
            self.drop_new()
            self.download()
            self.filestore()
            self.restore()
            self.update()
            self.neutralize()
            self.sanity()
            if self.args.rehearse:
                raise Skip("rehearsed", "rehearsal complete up to the swap; %s was not touched" % self.db)
            self.swap()
            self.cleanup_old()
            self.stamp_source()
            self.after_hooks()
            self.status.update(result="ok", message="%s now holds backup %s" % (self.db, self.status["backup_utc"]))
        except Skip as exc:
            self.status.update(result=exc.result, message=str(exc))
            if not self.swapped:
                self.cleanup_failed()
        except Failed as exc:
            self.status.update(result="failed", step=exc.step, message=str(exc))
            log("FAILED at %s: %s" % (exc.step, exc))
            if not self.swapped:
                self.cleanup_failed()
        except Exception as exc:  # unexpected: still record it, never leave the status at "running"
            self.status.update(result="failed", message="%s: %s" % (type(exc).__name__, exc))
            log("FAILED unexpectedly at %s: %s" % (self.status.get("step"), exc))
            if not self.swapped:
                self.cleanup_failed()
            raise
        finally:
            lock.close()
            self.finish()

    def cleanup_failed(self):
        try:
            self.drop_new()
        except Exception as exc:  # the live database is untouched; report and go on
            self.warnings.append("could not drop %s: %s" % (self.new, exc))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True, help="TOML file with the source, target and run settings")
    parser.add_argument("--filestore", action="store_true", help="copy the filestore tonight, not only on its days")
    parser.add_argument("--force", action="store_true", help="restore even if this backup is already restored")
    parser.add_argument("--check", action="store_true",
                        help="preflight only: read the backup, lock and disk; change nothing")
    parser.add_argument("--rehearse", action="store_true",
                        help="run everything up to the checks, then drop the copy; never swap, never stop Odoo")
    args = parser.parse_args()
    refresh = Refresh(tomllib.loads(path(args.config).read_text()), args)
    refresh.execute()
    print(json.dumps({k: refresh.status.get(k) for k in ("result", "step", "message")}, indent=2))
    sys.exit(1 if refresh.status["result"] == "failed" else 0)


if __name__ == "__main__":
    main()
