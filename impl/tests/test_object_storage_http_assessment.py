"""docs/object-storage-http-assessment.md's run evidence, committed as an
offline, deterministic regression suite (issue #193). Every case boots its
own ThreadingHTTPServer on an ephemeral loopback port -- no docker, no real
network -- mirroring test_cli_capability_http.py's harness."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from lnpl.cli import main as lnpl_main

from tests.test_network_driver import _ServerTestCase, _make_handler

STORE_UPLOAD_SOURCE = """
capability http Storage
    method put
    path "/objects/{}"
entity Upload
    field
        id UUID
        objectKey Text
        content Text
service StorageSvc
workflow StoreUpload
    call Storage with objectKey as p
"""

GET_PRESIGNED_URL_SOURCE = """
capability http Presign
    method post
entity PresignRequest
    field
        id UUID
        objectKey Text
service PresignSvc
workflow GetPresignedUrl
    call Presign as p
"""

DOWNLOAD_OBJECT_SOURCE = """
capability http Storage
    method get
entity DownloadRequest
    field
        id UUID
service StorageSvc
workflow DownloadObject
    call Storage as p
"""

SIGN_CLAUSE_SOURCE = """
capability http Storage
    method put
    sign sigv4
entity Upload
    field
        id UUID
        objectKey Text
service StorageSvc
workflow SignedUpload
    call Storage as p
"""

CHAINED_CALL_SOURCE = """
capability http Presign
    method post
entity PresignRequest
    field
        id UUID
        objectKey Text
service PresignSvc
workflow UploadViaPresignedUrl
    call Presign as p
    call p as q
"""


class ObjectStorageHttpAssessmentTest(_ServerTestCase):

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.dir = box.name

    def write_source(self, text, name="mod.lnpl"):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def write_payload(self, data, name="payload.json"):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return path

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = lnpl_main(argv)
        return rc, out.getvalue(), err.getvalue()

    # ---- normal: the JSON PUT body works, Content-Type is forced ----

    def test_json_put_body_reaches_the_mock_server_with_json_content_type(self):
        handler = _make_handler(status=200, body={"ok": True})
        url = self.start(handler)
        source = self.write_source(STORE_UPLOAD_SOURCE)
        payload = self.write_payload({
            "id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
            "objectKey": "report.pdf", "content": "hello world"})

        rc, out, err = self.run_cli(
            ["run", source, "--network", "http",
             "--endpoint", "Storage=%s" % url, "--payload", payload, "--json"])

        self.assertEqual(rc, 0, err)
        self.assertEqual(handler.received_methods[0], "PUT")
        self.assertEqual(handler.received_paths[0], "/objects/report.pdf")
        self.assertEqual(handler.received_headers[0].get("Content-Type"),
                         "application/json")
        self.assertEqual(handler.received[0], {
            "id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
            "objectKey": "report.pdf", "content": "hello world"})

    # ---- boundary: an object key containing "/" ----

    def test_an_object_key_containing_a_slash_is_percent_encoded_in_the_path(self):
        handler = _make_handler(status=200, body={"ok": True})
        url = self.start(handler)
        source = self.write_source(STORE_UPLOAD_SOURCE)
        payload = self.write_payload({
            "id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
            "objectKey": "uploads/2026/report.pdf", "content": "x"})

        rc, out, err = self.run_cli(
            ["run", source, "--network", "http",
             "--endpoint", "Storage=%s" % url, "--payload", payload, "--json"])

        self.assertEqual(rc, 0, err)
        self.assertEqual(handler.received_paths[0],
                         "/objects/uploads%2F2026%2Freport.pdf")

    # ---- boundary: an empty-string field round-trips (zero-length object) ----

    def test_an_empty_string_field_round_trips_inside_the_always_present_json_body(self):
        handler = _make_handler(status=200, body={"ok": True})
        url = self.start(handler)
        source = self.write_source(STORE_UPLOAD_SOURCE)
        payload = self.write_payload({
            "id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
            "objectKey": "empty.bin", "content": ""})

        rc, out, err = self.run_cli(
            ["run", source, "--network", "http",
             "--endpoint", "Storage=%s" % url, "--payload", payload, "--json"])

        self.assertEqual(rc, 0, err)
        self.assertEqual(handler.received[0]["content"], "")

    # ---- normal: a presigned URL field is bound from the JSON response ----

    def test_a_presigned_url_field_is_bound_from_the_json_response(self):
        fake_url = ("https://example-bucket.s3.example.com/report.pdf"
                    "?X-Amz-Signature=FAKESIGNATURE0000")
        handler = _make_handler(status=200, body={"url": fake_url})
        url = self.start(handler)
        source = self.write_source(GET_PRESIGNED_URL_SOURCE)
        payload = self.write_payload({
            "id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
            "objectKey": "report.pdf"})

        rc, out, err = self.run_cli(
            ["run", source, "--network", "http",
             "--endpoint", "Presign=%s" % url, "--payload", payload, "--json"])

        self.assertEqual(rc, 0, err)
        result = json.loads(out)
        self.assertEqual(result["result"]["bindings"]["p"]["url"], fake_url)

    # ---- error: a SigV4-style sign clause is rejected at compile time ----

    def test_a_sign_clause_is_rejected_at_compile_time(self):
        source = self.write_source(SIGN_CLAUSE_SOURCE)

        rc, out, err = self.run_cli(["compile", source])

        self.assertEqual(rc, 2)
        self.assertIn("'sign'", err)
        self.assertIn("method", err)

    # ---- error: a prior binding cannot be used as a dynamic call target ----

    def test_a_prior_binding_cannot_be_used_as_a_dynamic_call_target(self):
        handler = _make_handler(status=200, body={
            "url": "https://example-bucket.s3.example.com/report.pdf"})
        url = self.start(handler)
        source = self.write_source(CHAINED_CALL_SOURCE)
        payload = self.write_payload({
            "id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
            "objectKey": "report.pdf"})

        rc, out, err = self.run_cli(
            ["run", source, "--network", "http",
             "--endpoint", "Presign=%s" % url, "--payload", payload, "--json"])

        self.assertEqual(rc, 2)
        self.assertIn("'p'", err)
        self.assertIn("--endpoint", err)

    # ---- normal/boundary: non-JSON response (small and 1 MiB) binds as {} ----

    def test_a_non_json_response_binds_as_an_empty_dict_plus_status(self):
        source = self.write_source(DOWNLOAD_OBJECT_SOURCE)
        payload = self.write_payload({"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301"})

        small_handler = _make_handler(status=200, raw_body=b"not json at all")
        small_url = self.start(small_handler)
        rc, out, err = self.run_cli(
            ["run", source, "--network", "http",
             "--endpoint", "Storage=%s" % small_url, "--payload", payload, "--json"])
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)["result"]["bindings"]["p"], {"status": 200})

        large_handler = _make_handler(status=200, raw_body=b"x" * (1024 * 1024))
        large_url = self.start(large_handler)
        rc, out, err = self.run_cli(
            ["run", source, "--network", "http",
             "--endpoint", "Storage=%s" % large_url, "--payload", payload, "--json"])
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)["result"]["bindings"]["p"], {"status": 200})

    # ---- error: a non-2xx response and a transport failure both bind a
    #      branchable status ----

    def test_a_non_2xx_response_and_a_transport_failure_both_bind_a_branchable_status(self):
        source = self.write_source(STORE_UPLOAD_SOURCE)
        payload = self.write_payload({
            "id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
            "objectKey": "report.pdf", "content": "x"})

        error_handler = _make_handler(status=500, body={"error": "disk full"})
        error_url = self.start(error_handler)
        rc, out, err = self.run_cli(
            ["run", source, "--network", "http",
             "--endpoint", "Storage=%s" % error_url, "--payload", payload, "--json"])
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)["result"]["bindings"]["p"],
                         {"error": "disk full", "status": 500})

        rc, out, err = self.run_cli(
            ["run", source, "--network", "http",
             "--endpoint", "Storage=http://127.0.0.1:1/",
             "--payload", payload, "--json"])
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)["result"]["bindings"]["p"], {"status": 0})


if __name__ == "__main__":
    unittest.main()
