"""Offline tests for the example's integrity, version recovery and safety bounds."""

import hashlib
import unittest

from read_case import Client, NoRedirect, ReadFailure, SnapshotChanged

WORKSPACE = "22222222-2222-4222-8222-222222222222"
CASE = "33333333-3333-4333-8333-333333333333"
RAW = b"\xef\xbb\xbffield=0001\r\nsecond=line\n"
TOKEN = "cfin_read_" + "a" * 43


class SavedCase(Client):
    def __init__(self, *, change_once=False, tamper=False):
        super().__init__("https://consumer.example", TOKEN, WORKSPACE)
        self.change_once = change_once
        self.tamper = tamper
        self.reads = 0
        self.version = 1

    def get(self, path, params=None, *, raw=False):
        params = params or {}
        if path.endswith(CASE):
            if "case_version" not in params:
                self.reads += 1
            source = {
                "source_id": "one",
                "source_version": "1",
                "content_sha256": hashlib.sha256(RAW).hexdigest(),
                "byte_size": len(RAW),
            }
            return {
                "api_version": "v1",
                "case_id": CASE,
                "workspace_id": WORKSPACE,
                "case_version": self.version,
                "sources": [source],
                "result": None,
            }
        if path.endswith(("/activity", "/records")):
            if self.change_once:
                self.change_once = False
                self.version += 1
                raise SnapshotChanged("Changed")
            return {
                "api_version": "v1",
                "case_id": CASE,
                "case_version": self.version,
                "total": 0,
                "items": [],
                "next_cursor": None,
            }
        if raw:
            return RAW + (b"tampered" if self.tamper else b"")
        return {
            "api_version": "v1",
            "case_id": CASE,
            "case_version": self.version,
            "source_id": "one",
            "source_version": "1",
            "text": RAW.decode("utf-8"),
            "sha256": hashlib.sha256(RAW).hexdigest(),
            "byte_size": len(RAW),
        }


class ConsumerTests(unittest.TestCase):
    def test_original_bom_crlf_and_leading_zeroes_survive(self):
        bundle, originals = SavedCase().read_case(CASE)
        self.assertEqual(bundle["case"]["case_version"], 1)
        self.assertEqual(originals[0][1], RAW)

    def test_version_change_discards_old_pages_and_restarts_once(self):
        client = SavedCase(change_once=True)
        bundle, originals = client.read_case(CASE)
        self.assertEqual(client.reads, 2)
        self.assertEqual(bundle["case"]["case_version"], 2)
        self.assertEqual(originals[0][1], RAW)

    def test_tampered_download_rejected(self):
        with self.assertRaises(ReadFailure):
            SavedCase(tamper=True).read_case(CASE)

    def test_remote_http_and_credentials_in_origin_rejected(self):
        for origin in (
            "http://consumer.example",
            "https://user:secret@consumer.example",
            "https://consumer.example?token=secret",
        ):
            with self.subTest(origin=origin), self.assertRaises(ReadFailure):
                Client(origin, TOKEN, WORKSPACE)

    def test_redirect_refused_before_forwarding_credentials(self):
        with self.assertRaises(ReadFailure):
            NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example")

    def test_page_binding_change_rejected(self):
        client = SavedCase()
        pages = iter(
            [
                {
                    "api_version": "v1",
                    "case_id": CASE,
                    "case_version": 1,
                    "total": 2,
                    "items": [{}],
                    "next_cursor": "one",
                },
                {
                    "api_version": "v1",
                    "case_id": CASE,
                    "case_version": 2,
                    "total": 2,
                    "items": [{}],
                    "next_cursor": None,
                },
            ]
        )
        client.get = lambda *args, **kwargs: next(pages)
        with self.assertRaises(ReadFailure):
            client.pages("/api/v1/cases/" + CASE + "/records", {"case_version": 1})


if __name__ == "__main__":
    unittest.main()
