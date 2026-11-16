import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.core.management.base import CommandError

DRILL_PREFIX = "spled_drill_"
TRIGGER_FUNCTION = "registry_evidence_immutable"
TRIGGER_SQL = (
    "SELECT count(*) FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid "
    "WHERE p.proname = %s AND NOT t.tgisinternal"
)


# ---------- finding things ----------

def default_dir():
    configured = getattr(settings, "BACKUP_DIR", "")
    return Path(configured) if configured else Path(settings.BASE_DIR) / "backups"


def utc_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def scratch_db_name():
    return DRILL_PREFIX + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def manifest_path(dump):
    return Path(str(dump) + ".json")


def find_tool(name):
    path = shutil.which(name, path=getattr(settings, "PG_BIN_DIR", "") or None)
    if not path:
        raise CommandError(
            f"Could not find {name}. Install the PostgreSQL client tools, "
            "or set PG_BIN_DIR to the folder that contains them."
        )
    return path


# ---------- connection details ----------

def connection_parts(alias="default"):
    db = settings.DATABASES[alias]
    return {
        "host": db.get("HOST") or "localhost",
        "port": str(db.get("PORT") or 5432),
        "user": db.get("USER") or "",
        "password": db.get("PASSWORD") or "",
        "dbname": db["NAME"],
        "options": db.get("OPTIONS") or {},
    }


def host_args(parts):
    """Command-line arguments. The password is deliberately NOT here."""
    return ["--host", parts["host"], "--port", parts["port"], "--username", parts["user"]]


def tool_env(parts):
    env = dict(os.environ)
    if parts["password"]:
        env["PGPASSWORD"] = parts["password"]
    sslmode = parts["options"].get("sslmode")
    if sslmode:
        env["PGSSLMODE"] = str(sslmode)
    return env


def database_url(parts, dbname):
    auth = quote(parts["user"], safe="")
    if parts["password"]:
        auth += ":" + quote(parts["password"], safe="")
    url = f"postgis://{auth}@{parts['host']}:{parts['port']}/{dbname}"
    sslmode = parts["options"].get("sslmode")
    if sslmode:
        url += f"?sslmode={sslmode}"
    return url


def run_tool(args, env):
    result = subprocess.run(args, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        lines = (result.stderr or result.stdout or "").strip().splitlines()
        detail = lines[-1] if lines else f"exit code {result.returncode}"
        raise CommandError(f"{Path(args[0]).stem} failed: {detail}")
    return result.stdout


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------- what the manifest records ----------

def _models():
    from django.contrib.auth import get_user_model

    from audit.models import AuditEvent
    from registry.models import EvidenceEntry, EvidencePhoto, Site

    return {
        "sites": Site,
        "evidence_entries": EvidenceEntry,
        "evidence_photos": EvidencePhoto,
        "audit_events": AuditEvent,
        "users": get_user_model(),
    }


def table_names():
    return {key: model._meta.db_table for key, model in _models().items()}


def live_counts():
    return {key: model.objects.count() for key, model in _models().items()}


def live_trigger_count():
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(TRIGGER_SQL, [TRIGGER_FUNCTION])
        return cursor.fetchone()[0]


def make_manifest(dump, parts):
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database": parts["dbname"],
        "file": Path(dump).name,
        "sha256": sha256_of(dump),
        "size_bytes": Path(dump).stat().st_size,
        "tables": table_names(),
        "counts": live_counts(),
        "immutable_triggers": live_trigger_count(),
    }
    manifest_path(dump).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


# ---------- restoring ----------

def filter_restore_list(listing):
    """Leave out what the scratch database already has or fills itself:
    the PostGIS extension, and the standard coordinate-system table."""
    kept = []
    for line in listing.splitlines():
        if line.startswith(";"):
            kept.append(line)
        elif " EXTENSION " in line or "TABLE DATA public spatial_ref_sys" in line:
            continue
        else:
            kept.append(line)
    return "\n".join(kept) + "\n"


def compare_with_manifest(facts, manifest):
    problems = []
    for key, expected in manifest.get("counts", {}).items():
        got = facts["counts"].get(key)
        if got != expected:
            problems.append(f"{key}: the backup had {expected}, the restored copy has {got}")
    if "immutable_triggers" in manifest and facts.get("immutable_triggers") != manifest["immutable_triggers"]:
        problems.append(
            f"append-only triggers: the backup had {manifest['immutable_triggers']}, "
            f"the restored copy has {facts.get('immutable_triggers')}"
        )
    return problems


def _connect(parts, dbname, autocommit=False):
    import psycopg

    kwargs = dict(host=parts["host"], port=parts["port"], user=parts["user"],
                  dbname=dbname, autocommit=autocommit)
    if parts["password"]:
        kwargs["password"] = parts["password"]
    sslmode = parts["options"].get("sslmode")
    if sslmode:
        kwargs["sslmode"] = sslmode
    return psycopg.connect(**kwargs)


def create_scratch_db(parts, name):
    from psycopg import sql

    try:
        with _connect(parts, "postgres", autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    except Exception as exc:
        raise CommandError(
            f"Could not create the scratch database ({type(exc).__name__}). "
            "The database user needs permission to create databases."
        )


def install_postgis(parts, name):
    try:
        with _connect(parts, name, autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    except Exception as exc:
        raise CommandError(f"Could not enable PostGIS in the scratch database ({type(exc).__name__}).")


def drop_scratch_db(parts, name):
    """Only ever drops a database this drill created."""
    from psycopg import sql

    if not name.startswith(DRILL_PREFIX) or name == parts["dbname"]:
        raise CommandError(f"Refusing to drop {name}: it is not a drill database.")
    try:
        with _connect(parts, "postgres", autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
    except Exception as exc:
        raise CommandError(f"Could not remove scratch database {name} ({type(exc).__name__}). Drop it by hand.")


def scratch_facts(parts, name, tables):
    from psycopg import sql

    with _connect(parts, name) as conn:
        counts = {}
        for key, table in tables.items():
            row = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()
            counts[key] = row[0]
        triggers = conn.execute(TRIGGER_SQL, [TRIGGER_FUNCTION]).fetchone()[0]
    return {"counts": counts, "immutable_triggers": triggers}


def run_check_evidence(parts, name):
    env = tool_env(parts)
    env["DATABASE_URL"] = database_url(parts, name)
    manage = Path(settings.BASE_DIR) / "manage.py"
    result = subprocess.run(
        [sys.executable, str(manage), "check_evidence"],
        env=env, capture_output=True, text=True,
    )
    return result.returncode, ((result.stdout or "") + (result.stderr or "")).strip()


def run_drill(dump_path, keep=False, log=print):
    dump = Path(dump_path)
    if not dump.is_file():
        raise CommandError(f"Backup file not found: {dump}")
    mpath = manifest_path(dump)
    if not mpath.is_file():
        raise CommandError(f"No manifest next to the backup ({mpath.name}). A backup without it can't be checked.")
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    if sha256_of(dump) != manifest.get("sha256"):
        raise CommandError("The backup file does not match its manifest: it was changed or damaged after it was made.")
    log("Backup file matches its manifest.")

    parts = connection_parts()
    env = tool_env(parts)
    pg_restore = find_tool("pg_restore")
    name = scratch_db_name()

    create_scratch_db(parts, name)
    log(f"Created scratch database {name}.")
    list_file = None
    try:
        install_postgis(parts, name)
        listing = run_tool([pg_restore, "--list", str(dump)], env)
        with tempfile.NamedTemporaryFile("w", suffix=".list", delete=False, encoding="utf-8") as tmp:
            tmp.write(filter_restore_list(listing))
            list_file = tmp.name
        run_tool(
            [pg_restore, *host_args(parts), "--no-password", "--dbname", name,
             "--no-owner", "--no-acl", "--exit-on-error", "--use-list", list_file, str(dump)],
            env,
        )
        log("Restored into the scratch database.")

        try:
            facts = scratch_facts(parts, name, manifest.get("tables", {}))
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(
                f"Could not read the restored copy ({type(exc).__name__}). "
                "The restore did not recreate the expected tables. "
                "Run again with --keep to inspect the scratch database."
            )
        problems = compare_with_manifest(facts, manifest)
        if problems:
            raise CommandError("Restore drill FAILED:\n- " + "\n- ".join(problems))
        log("Row counts and append-only triggers match the backup.")

        code, output = run_check_evidence(parts, name)
        if code != 0:
            raise CommandError("Restore drill FAILED: check_evidence found problems in the restored copy:\n" + output)
        log("check_evidence: " + (output.splitlines()[-1] if output else "no problems."))
    finally:
        if list_file:
            try:
                os.unlink(list_file)
            except OSError:
                pass
        if keep:
            log(f"Kept scratch database {name}. Remove it when you are done.")
        else:
            try:
                drop_scratch_db(parts, name)
                log("Removed the scratch database.")
            except CommandError as exc:
                log(str(exc))