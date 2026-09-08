"""Check CLI and downstream typing against the built wheel, without network access."""

import argparse
import json
import subprocess
import sys
import sysconfig
import tempfile
import venv
from pathlib import Path


def check(wheel: Path, uv: str) -> None:
    with tempfile.TemporaryDirectory(prefix="long-swe-wheel-") as temporary:
        root = Path(temporary).resolve()
        if root.parent != Path(tempfile.gettempdir()).resolve():
            raise RuntimeError("unexpected temporary environment location")
        environment = root / "environment"
        venv.EnvBuilder(with_pip=False).create(environment)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        subprocess.run(
            [uv, "pip", "install", "--offline", "--no-deps", "--python", str(python), str(wheel)],
            check=True,
        )
        installed = json.loads(
            subprocess.check_output(
                [
                    str(python),
                    "-I",
                    "-c",
                    "import json, sysconfig; print(json.dumps(sysconfig.get_paths()))",
                ],
                text=True,
            )
        )
        # Reuse locked development dependencies, without processing their editable-project .pth.
        # The package under test must resolve from the new environment's installed wheel.
        (Path(installed["purelib"]) / "locked_dependencies.pth").write_text(
            sysconfig.get_paths()["purelib"] + "\n",
            encoding="utf-8",
        )
        location = subprocess.check_output(
            [
                str(python),
                "-I",
                "-c",
                "import long_horizon_swe; print(long_horizon_swe.__file__)",
            ],
            text=True,
        ).strip()
        if not Path(location).resolve().is_relative_to(environment):
            raise RuntimeError("consumer resolved a source checkout instead of the installed wheel")
        subprocess.run([str(python), "-I", "-m", "long_horizon_swe", "--version"], check=True)
        config = root / "mypy.ini"
        config.write_text("[mypy]\nstrict = True\n", encoding="utf-8")
        consumer = root / "consumer.py"
        source = (
            "from pathlib import Path\n"
            "from long_horizon_swe.config.loader import load_task\n"
            "from long_horizon_swe.core.task import TaskSpec\n"
            "def read(path: Path) -> TaskSpec:\n    return load_task(path)\n"
        )
        consumer.write_text(source, encoding="utf-8")
        command = [
            sys.executable,
            "-m",
            "mypy",
            "--no-incremental",
            "--config-file",
            str(config),
            "--python-executable",
            str(python),
            str(consumer),
        ]
        subprocess.run(command, cwd=root, check=True)
        consumer.write_text(source + "load_task('wrong-path-type')\n", encoding="utf-8")
        rejected = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
        if rejected.returncode != 1 or "[arg-type]" not in rejected.stdout:
            raise RuntimeError("installed type information did not reject an invalid API call")
        print("Installed-wheel CLI and consumer typing passed; invalid API argument rejected.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--uv", default="uv", help="uv executable used for offline wheel installation"
    )
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    wheels = list((project / "dist").glob("long_horizon_swe_lab-*.whl"))
    if len(wheels) != 1:
        raise ValueError("build exactly one framework wheel in dist/ before this check")
    check(wheels[0], args.uv)


if __name__ == "__main__":
    main()
