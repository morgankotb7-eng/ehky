import base64
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from ehky import pipeline, ui

TOKEN = "test-token"


class UiServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.job = ui.Job()
        handler = ui.make_handler(TOKEN, 0, self.job, Path(self.tmp.name))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        # rebuild the handler now that the real port is known (Host header check uses it)
        self.server.RequestHandlerClass = ui.make_handler(TOKEN, self.port, self.job, Path(self.tmp.name))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, path, data=None, token=TOKEN, host=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data)
        if token:
            req.add_header("X-Ehky-Token", token)
        if host:
            req.add_header("Host", host)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return res.status, res.read()
        except urllib.error.HTTPError as err:
            return err.code, err.read()

    def test_page_is_arabic_rtl(self):
        status, body = self.request("/", token=None)
        self.assertEqual(status, 200)
        self.assertIn(b'dir="rtl"', body)

    def test_api_needs_token_and_local_host(self):
        self.assertEqual(self.request("/api/job", token=None)[0], 403)
        self.assertEqual(self.request("/api/job", token="wrong")[0], 403)
        self.assertEqual(self.request("/api/job", host="evil.example")[0], 403)
        self.assertEqual(self.request("/api/job")[0], 200)

    def test_rejects_bad_files_and_bad_json(self):
        bad = {"script": "مرحبا.", "media": [{"name": "x.exe", "data": base64.b64encode(b"x").decode()}]}
        status, body = self.request("/api/make", json.dumps(bad).encode())
        self.assertEqual(status, 400)
        self.assertIn("not allowed", json.loads(body)["error"])
        self.assertEqual(self.request("/api/make", b"not json")[0], 400)
        malformed = {"script": "مرحبا.", "music": "not-an-object", "media": ["also-wrong"]}
        self.assertEqual(self.request("/api/make", json.dumps(malformed).encode())[0], 400)
        self.assertEqual(self.job.snapshot()["state"], "idle")

    def test_full_job_with_a_fake_renderer(self):
        def fake_render(plan, timeout=1800, log=print):
            log("[2/2] Rendering the video...")
            plan.out.write_bytes(b"fake mp4")
            return 3.0

        payload = {
            "script": "تعرف إن العسل مبيبوظش؟",
            "engine": "edge",
            "voice": "ar-EG-SalmaNeural",
            "aspect": "1:1",
            "subtitles": False,
            "media": [{"name": "photo.png", "data": base64.b64encode(b"png").decode()}],
            "music": {"name": "song.mp3", "data": base64.b64encode(b"mp3").decode()},
            "music_volume": 0.5,
        }
        with mock.patch.object(pipeline, "render", side_effect=fake_render):
            status, body = self.request("/api/make", json.dumps(payload).encode())
            self.assertEqual(status, 202, body)
            for _ in range(50):
                if self.job.snapshot()["state"] != "running":
                    break
                time.sleep(0.05)
        snap = self.job.snapshot()
        self.assertEqual(snap["state"], "done", snap)
        status, video = self.request(f"/api/video?t={TOKEN}", token=None)
        self.assertEqual((status, video), (200, b"fake mp4"))
        media = list((Path(self.tmp.name) / "project" / "media").iterdir())
        self.assertEqual([p.name for p in media], ["00.png"])  # server-chosen names only


if __name__ == "__main__":
    unittest.main()
