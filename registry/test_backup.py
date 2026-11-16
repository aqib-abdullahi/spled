import hashlib
import io
import json
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import unquote, urlparse

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from registry import backup

PARTS = dict(host="db.example", port="5432", user="app", password="s3cret",
             dbname="spled", options={"sslmode": "require"})

LISTING = (
    "; Archive created\n"
    "1; 1 2 TABLE public registry_site app\n"
    "2; 3 4 EXTENSION - postgis\n"
    "3; 5 6 COMMENT - EXTENSION postgis\n"
    "4; 7 8 TABLE DATA public spatial_ref_sys app\n"
    "5; 9 10 TABLE DATA public registry_site app\n"
)
GOOD_FACTS = {"counts": {"sites": 2, "users": 1}, "immutable_triggers": 3}


class PureFunctionTests(SimpleTestCase):
    def test_filter_drops_extension_entries(self):
        self.assertNotIn("EXTENSION", backup.filter_restore_list(LISTING))

    def test_filter_keeps_comments_and_other_entries(self):
        result = backup.filter_restore_list(LISTING)
        self.assertIn("; Archive created", result)
        self.assertIn("TABLE public registry_site", result)
        self.assertIn("TABLE DATA public registry_site", result)

    def test_filter_drops_the_standard_coordinate_table_rows(self):
        self.assertNotIn("spatial_ref_sys", backup.filter_restore_list(LISTING))

    def test_password_is_in_the_environment_not_the_arguments(self):
        self.assertNotIn("s3cret", " ".join(backup.host_args(PARTS)))
        self.assertEqual(backup.tool_env(PARTS)["PGPASSWORD"], "s3cret")

    def test_sslmode_is_passed_through(self):
        self.assertEqual(backup.tool_env(PARTS)["PGSSLMODE"], "require")

    def test_database_url_quotes_special_characters(self):
        url = backup.database_url(dict(PARTS, user="ap p", password="p@ss/w:rd"), "x")
        parsed = urlparse(url)
        self.assertEqual(parsed.scheme, "postgis")
        self.assertEqual(unquote(parsed.password), "p@ss/w:rd")
        self.assertEqual(parsed.hostname, "db.example")
        self.assertEqual(parsed.path, "/x")
        self.assertIn("sslmode=require", url)

    def test_scratch_names_carry_the_safe_prefix(self):
        self.assertTrue(backup.scratch_db_name().startswith(backup.DRILL_PREFIX))

    def test_drop_refuses_databases_without_the_prefix(self):
        for name in ("spled", "postgres", "spled_prod"):
            with self.subTest(name=name):
                with self.assertRaises(CommandError):
                    backup.drop_scratch_db(PARTS, name)

    def test_missing_tool_says_how_to_fix_it(self):
        with mock.patch("registry.backup.shutil.which", return_value=None):
            with self.assertRaises(CommandError) as ctx:
                backup.find_tool("pg_dump")
        self.assertIn("PG_BIN_DIR", str(ctx.exception))

    def test_tool_failure_shows_the_last_line(self):
        failed = SimpleNamespace(returncode=1, stdout="", stderr="first\nlast line here\n")
        with mock.patch("registry.backup.subprocess.run", return_value=failed):
            with self.assertRaises(CommandError) as ctx:
                backup.run_tool(["/x/pg_dump"], {})
        self.assertIn("last line here", str(ctx.exception))
        self.assertIn("pg_dump", str(ctx.exception))

    def test_compare_reports_each_difference(self):
        manifest = {"counts": {"sites": 2, "users": 1}, "immutable_triggers": 3}
        facts = {"counts": {"sites": 1, "users": 1}, "immutable_triggers": 2}
        problems = backup.compare_with_manifest(facts, manifest)
        self.assertEqual(len(problems), 2)
        joined = " ".join(problems)
        self.assertIn("sites", joined)
        self.assertIn("triggers", joined)


class BackupCommandTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    @staticmethod
    def fake_dump(args, env):
        Path(args[args.index("--file") + 1]).write_bytes(b"dump-bytes")
        return ""

    def run_backup(self, side_effect=None):
        out = io.StringIO()
        with mock.patch("registry.backup.find_tool", return_value="pg_dump"), \
             mock.patch("registry.backup.connection_parts", return_value=PARTS), \
             mock.patch("registry.backup.run_tool", side_effect=side_effect or self.fake_dump) as run:
            call_command("backup_db", output_dir=self.tmp, stdout=out)
        return run, out.getvalue()

    def dumps(self):
        return sorted(Path(self.tmp).glob("spled-*.dump"))

    def test_writes_a_dump_and_a_manifest(self):
        _run, out = self.run_backup()
        dumps = self.dumps()
        self.assertEqual(len(dumps), 1)
        manifest = json.loads(Path(str(dumps[0]) + ".json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["sha256"], hashlib.sha256(b"dump-bytes").hexdigest())
        self.assertEqual(manifest["size_bytes"], 10)
        self.assertIn("Backup written", out)

    def test_manifest_has_counts_and_trigger_count(self):
        self.run_backup()
        manifest = json.loads(Path(str(self.dumps()[0]) + ".json").read_text(encoding="utf-8"))
        self.assertEqual(
            set(manifest["counts"]),
            {"sites", "evidence_entries", "evidence_photos", "audit_events", "users"},
        )
        self.assertEqual(set(manifest["tables"]), set(manifest["counts"]))
        self.assertIsInstance(manifest["immutable_triggers"], int)

    def test_password_never_appears_in_the_command_line(self):
        run, _out = self.run_backup()
        args, env = run.call_args.args
        self.assertNotIn("s3cret", " ".join(args))
        self.assertEqual(env["PGPASSWORD"], "s3cret")
        self.assertIn("--format=custom", args)

    def test_never_overwrites_an_existing_backup(self):
        with mock.patch("registry.backup.utc_stamp", return_value="FIXED"):
            self.run_backup()
            with self.assertRaises(CommandError) as ctx:
                self.run_backup()
        self.assertIn("already exists", str(ctx.exception))

    def test_failed_dump_leaves_no_partial_file(self):
        def partial_then_fail(args, env):
            Path(args[args.index("--file") + 1]).write_bytes(b"half")
            raise CommandError("pg_dump failed: boom")

        with self.assertRaises(CommandError):
            self.run_backup(side_effect=partial_then_fail)
        self.assertEqual(self.dumps(), [])


class RestoreDrillTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.dump = Path(self.tmp) / "spled-test.dump"
        self.dump.write_bytes(b"data")
        self.manifest = Path(str(self.dump) + ".json")

    def write_manifest(self, sha=None):
        self.manifest.write_text(json.dumps({
            "sha256": sha or hashlib.sha256(b"data").hexdigest(),
            "counts": {"sites": 2, "users": 1},
            "tables": {"sites": "registry_site", "users": "accounts_user"},
            "immutable_triggers": 3,
        }), encoding="utf-8")

    def drill(self, facts=None, restore_error=None, evidence=(0, "No problems."), keep=False):
        self.write_manifest()
        self.order, self.list_text, self.restore_args = [], None, None

        def note(label):
            return mock.Mock(side_effect=lambda *a, **k: self.order.append(label))

        def run_tool(args, env):
            if "--list" in args:
                self.order.append("list")
                return LISTING
            self.order.append("restore")
            self.restore_args = args
            self.list_text = Path(args[args.index("--use-list") + 1]).read_text(encoding="utf-8")
            if restore_error:
                raise CommandError(restore_error)
            return ""

        self.create, self.drop = note("create"), note("drop")
        self.check = mock.Mock(side_effect=lambda *a, **k: (self.order.append("evidence"), evidence)[1])
        self.facts = mock.Mock(side_effect=lambda *a, **k: (self.order.append("facts"), facts or GOOD_FACTS)[1])
        out = io.StringIO()
        with mock.patch.multiple(
            "registry.backup",
            find_tool=mock.Mock(return_value="pg_restore"),
            connection_parts=mock.Mock(return_value=PARTS),
            run_tool=run_tool,
            create_scratch_db=self.create,
            install_postgis=note("postgis"),
            drop_scratch_db=self.drop,
            scratch_facts=self.facts,
            run_check_evidence=self.check,
        ):
            args = [str(self.dump)] + (["--keep"] if keep else [])
            call_command("restore_drill", *args, stdout=out)
        return out.getvalue()

    def test_missing_manifest_is_refused(self):
        with self.assertRaises(CommandError) as ctx:
            call_command("restore_drill", str(self.dump), stdout=io.StringIO())
        self.assertIn("manifest", str(ctx.exception))

    def test_changed_backup_file_is_refused(self):
        self.write_manifest(sha="0" * 64)
        with self.assertRaises(CommandError) as ctx:
            call_command("restore_drill", str(self.dump), stdout=io.StringIO())
        self.assertIn("does not match", str(ctx.exception))

    def test_happy_path_runs_every_step_in_order_and_cleans_up(self):
        out = self.drill()
        self.assertEqual(
            self.order,
            ["create", "postgis", "list", "restore", "facts", "evidence", "drop"],
        )
        name = self.create.call_args.args[1]
        self.assertTrue(name.startswith(backup.DRILL_PREFIX))
        self.assertEqual(self.drop.call_args.args[1], name)
        self.assertEqual(self.check.call_args.args[1], name)
        self.assertEqual(self.restore_args[self.restore_args.index("--dbname") + 1], name)
        self.assertIn("--exit-on-error", self.restore_args)
        self.assertIn("Restore drill PASSED", out)

    def test_extensions_are_left_out_of_the_restore_list(self):
        self.drill()
        self.assertNotIn("EXTENSION", self.list_text)
        self.assertNotIn("spatial_ref_sys", self.list_text)
        self.assertIn("registry_site", self.list_text)
        self.assertIn("; Archive created", self.list_text)

    def test_scratch_database_is_dropped_even_when_the_restore_fails(self):
        with self.assertRaises(CommandError):
            self.drill(restore_error="pg_restore failed: boom")
        self.drop.assert_called_once()

    def test_count_mismatch_fails_the_drill(self):
        bad = {"counts": {"sites": 1, "users": 1}, "immutable_triggers": 3}
        with self.assertRaises(CommandError) as ctx:
            self.drill(facts=bad)
        self.assertIn("sites", str(ctx.exception))
        self.drop.assert_called_once()
        self.check.assert_not_called()

    def test_evidence_check_failure_fails_the_drill(self):
        with self.assertRaises(CommandError) as ctx:
            self.drill(evidence=(1, "Site 1, entry 5: hash mismatch"))
        self.assertIn("hash mismatch", str(ctx.exception))
        self.drop.assert_called_once()

    def test_keep_leaves_the_scratch_database(self):
        out = self.drill(keep=True)
        self.drop.assert_not_called()
        self.assertIn(self.create.call_args.args[1], out)


class WiringTests(SimpleTestCase):
    def test_backups_folder_is_not_committed(self):
        text = (Path(settings.BASE_DIR) / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("backups/", text)

    @override_settings(BACKUP_DIR="")
    def test_default_backup_folder_is_inside_the_project(self):
        folder = backup.default_dir()
        self.assertEqual(folder.name, "backups")
        self.assertEqual(folder.parent, Path(settings.BASE_DIR))

class RealLineBreakTests(SimpleTestCase):
    def test_filter_output_has_real_line_breaks(self):
        result = backup.filter_restore_list(LISTING)
        self.assertEqual(len(result.splitlines()), 3)
        self.assertNotIn("\\n", result)  # a literal backslash followed by n
        self.assertEqual(result.splitlines()[0], "; Archive created")
        self.assertTrue(result.endswith("\n"))

    def test_every_kept_line_is_a_whole_list_entry(self):
        for line in backup.filter_restore_list(LISTING).splitlines():
            self.assertTrue(line.startswith(";") or line.split(";")[0].isdigit(), line)


class UnreadableRestoreTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.dump = Path(self.tmp) / "x.dump"
        self.dump.write_bytes(b"data")
        Path(str(self.dump) + ".json").write_text(json.dumps({
            "sha256": hashlib.sha256(b"data").hexdigest(),
            "counts": {"sites": 2},
            "tables": {"sites": "registry_site"},
        }), encoding="utf-8")

    def run_drill(self, facts_effect):
        self.drop = mock.Mock()
        with mock.patch.multiple(
            "registry.backup",
            find_tool=mock.Mock(return_value="pg_restore"),
            connection_parts=mock.Mock(return_value=PARTS),
            run_tool=mock.Mock(return_value=LISTING),
            create_scratch_db=mock.Mock(),
            install_postgis=mock.Mock(),
            drop_scratch_db=self.drop,
            scratch_facts=mock.Mock(side_effect=facts_effect),
            run_check_evidence=mock.Mock(return_value=(0, "ok")),
        ):
            call_command("restore_drill", str(self.dump), stdout=io.StringIO())

    def test_missing_tables_become_a_clear_error_and_the_scratch_db_is_dropped(self):
        with self.assertRaises(CommandError) as ctx:
            self.run_drill(RuntimeError("relation does not exist"))
        self.assertIn("did not recreate", str(ctx.exception))
        self.drop.assert_called_once()

    def test_failure_messages_have_real_line_breaks(self):
        bad = {"counts": {"sites": 1}, "immutable_triggers": 0}
        with self.assertRaises(CommandError) as ctx:
            self.run_drill([bad])
        message = str(ctx.exception)
        self.assertIn("FAILED:\n- ", message)
        self.assertNotIn("\\n", message)