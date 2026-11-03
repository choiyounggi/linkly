"""The backup deployment examples of issue #238 are hand-written; these tests
pin their load-bearing literals and refuse literal credentials."""

import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEPLOY = os.path.join(REPO, "examples", "deploy")

EXAMPLE_FILES = ["litestream-compose.yml", "litestream.yml", "pg-dump-cronjob.yaml"]

LITERAL_CREDENTIAL = re.compile(
    r"(?i)(password|secret_access_key|access_key_id)\s*[:=]\s*[\"']?[A-Za-z0-9]")


def read(name):
    with open(os.path.join(DEPLOY, name), encoding="utf-8") as fh:
        return fh.read()


class LitestreamExampleTest(unittest.TestCase):

    def test_the_compose_file_runs_litestream_beside_the_app(self):
        text = read("litestream-compose.yml")
        for literal in ("image: litestream/litestream:0.5.17",
                        "command: replicate",
                        "- ./litestream.yml:/etc/litestream.yml:ro",
                        "- lnpl-data:/data",
                        'LNPL_BACKEND: "sqlite:/data/store.db"',
                        '- "127.0.0.1:8000:8000"',
                        "${LITESTREAM_REPLICA_URL:?set LITESTREAM_REPLICA_URL}"):
            self.assertIn(literal, text)

    def test_the_litestream_config_replicates_the_shared_store(self):
        text = read("litestream.yml")
        self.assertIn("- path: /data/store.db", text)
        self.assertIn("url: ${LITESTREAM_REPLICA_URL}", text)


class CronJobExampleTest(unittest.TestCase):

    def test_the_cronjob_runs_pg_dump_without_overlap(self):
        text = read("pg-dump-cronjob.yaml")
        for literal in ("kind: CronJob",
                        "concurrencyPolicy: Forbid",
                        "backoffLimit: 0",
                        "activeDeadlineSeconds: 3600",
                        "image: postgres:16",
                        "pg_dump -Fc -f /backup/",
                        "secretKeyRef:",
                        "name: lnpl-pg-dump",
                        "claimName: lnpl-pg-backups"):
            self.assertIn(literal, text)


class NoLiteralCredentialTest(unittest.TestCase):

    def test_no_example_file_carries_a_literal_credential(self):
        for name in EXAMPLE_FILES:
            self.assertTrue(os.path.isfile(os.path.join(DEPLOY, name)), name)
            hits = [line for line in read(name).splitlines()
                    if LITERAL_CREDENTIAL.search(line)]
            self.assertEqual([], hits, name)

    def test_the_guard_matches_a_literal_and_skips_an_interpolation(self):
        # Positive control: the guard is live, not vacuously quiet.
        self.assertIsNotNone(LITERAL_CREDENTIAL.search("PGPASSWORD: hunter2-example"))
        self.assertIsNone(LITERAL_CREDENTIAL.search(
            "LITESTREAM_ACCESS_KEY_ID: ${LITESTREAM_ACCESS_KEY_ID:?set "
            "LITESTREAM_ACCESS_KEY_ID}"))

    def test_the_file_list_is_not_empty(self):
        self.assertGreaterEqual(len(EXAMPLE_FILES), 3)


if __name__ == "__main__":
    unittest.main()
