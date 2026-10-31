"""Inspect and install release archives in clean consumers. No credentials or live posts."""

from pathlib import Path
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = json.loads((ROOT / "sdks/javascript/package.json").read_text())
VERSION = PACKAGE["version"]


def run(*args, cwd=ROOT):
    subprocess.run(args, cwd=cwd, check=True)


def main():
    for manifest in ("pyproject.toml", "sdks/rust/Cargo.toml"):
        assert re.search(r'^version = "' + re.escape(VERSION) + r'"$', (ROOT / manifest).read_text(), re.M)
    wheel = ROOT / "dist" / f"socialpublishkit-{VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as archive:
        metadata = archive.read(f"socialpublishkit-{VERSION}.dist-info/METADATA").decode()
        assert "License-Expression: MIT" in metadata
        assert "Requires-Dist:" not in metadata, "Python runtime dependencies changed"
        assert archive.read(f"socialpublishkit-{VERSION}.dist-info/licenses/LICENSE") == (ROOT / "LICENSE").read_bytes()
        assert all(name.startswith(("socialpublishkit/", f"socialpublishkit-{VERSION}.dist-info/")) for name in archive.namelist())
    sdist = ROOT / "dist" / f"socialpublishkit-{VERSION}.tar.gz"
    with tarfile.open(sdist) as archive:
        names = archive.getnames()
        assert f"socialpublishkit-{VERSION}/examples/gateway.json" in names
        assert f"socialpublishkit-{VERSION}/docs/usage.md" in names
    run("npm", "pack", "--pack-destination", str(ROOT / "dist"), cwd=ROOT / "sdks/javascript")
    npm_archive = ROOT / "dist" / f"socialpublishkit-{VERSION}.tgz"
    with tarfile.open(npm_archive) as archive:
        assert set(archive.getnames()) == {f"package/{name}" for name in ("LICENSE", "README.md", "index.js", "index.d.ts", "package.json")}
        assert archive.extractfile("package/LICENSE").read() == (ROOT / "LICENSE").read_bytes()
    with tempfile.TemporaryDirectory(prefix="socialpublishkit-install-") as directory:
        root = Path(directory)
        env = root / "venv"
        venv.create(env, with_pip=True)
        python = env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        run(str(python), "-m", "pip", "install", "--no-deps", str(wheel), cwd=root)
        run(str(python), "-c", f"import socialpublishkit; assert socialpublishkit.__version__ == '{VERSION}'; from socialpublishkit import YouTubeOptions; assert YouTubeOptions().privacy == 'private'", cwd=root)
        run(str(python), "-m", "socialpublishkit", "--help", cwd=root)
        run("npm", "install", "--ignore-scripts", "--no-audit", "--no-fund", str(npm_archive), cwd=root)
        run("node", "--input-type=module", "-e", "import { SocialClient } from 'socialpublishkit'; const c = new SocialClient({token:'test-token'}); if (JSON.stringify(c) !== '{}') throw Error('Credential serialization');", cwd=root)
    print(f"Release {VERSION}: license, archive contents, Python wheel and npm consumer imports verified.")


if __name__ == "__main__":
    main()
