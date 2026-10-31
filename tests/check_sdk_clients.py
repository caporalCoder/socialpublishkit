"""Run both clients against the real gateway with a fake provider. Never loads credentials."""
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from socialpublishkit import Account, Platform, PublishResult, PublishStatus
from socialpublishkit.gateway import Gateway

class FakePublisher:
    calls = 0
    def publish(self, account, post, *, tiktok=None, youtube=None):
        assert post.video.read_bytes() == b"fake-mp4"
        self.calls += 1
        if account.platform == Platform.YOUTUBE:
            assert youtube.privacy == 'unlisted' and youtube.made_for_kids is True
            return PublishResult(account.platform, PublishStatus.UPLOADED, "fake-youtube")
        return PublishResult(account.platform, PublishStatus.DRAFT_DELIVERED, "fake-draft")

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as directory:
    video = Path(directory) / "fixture.mp4"
    video.write_bytes(b"fake-mp4")
    publisher = FakePublisher()
    gateway = Gateway(publisher, {"tiktok": Account(Platform.TIKTOK, "fake", "123", "Test"),
                                 "youtube": Account(Platform.YOUTUBE, "fake", "channel", "Test")},
                      token="test-gateway-token-" * 2, state_dir=directory)
    server = gateway.server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = dict(os.environ, SOCIALPUBLISHKIT_TEST_GATEWAY=f"http://127.0.0.1:{server.server_port}", SOCIALPUBLISHKIT_TEST_VIDEO=str(video))
    try:
        subprocess.run(["node", "sdks/javascript/test/gateway-smoke.mjs"], cwd=root, env=env, check=True)
        subprocess.run(["cargo", "+1.98.0", "run", "--quiet", "--locked", "--example", "gateway_smoke"],
                       cwd=root / "sdks/rust", env=env, check=True)
        assert publisher.calls == 4, f"Expected two provider calls per SDK, got {publisher.calls}"
        print("Cross-language test passed: TikTok and YouTube, two clients, four calls, duplicates suppressed.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        gateway.close()
