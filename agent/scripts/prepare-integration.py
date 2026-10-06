"""Prepare the fixed isolated Gianna test stack. Preserve its DB and fixture users.

Never targets idl-tickets-e2e or downgrades/reset/deletes a schema or volume.
"""

from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
fixtures = root / "artifacts/design-check-users.json"
compose = [
    "docker",
    "compose",
    "-p",
    "idl-tickets-design-check",
    "-f",
    str(root / "compose.yaml"),
    "-f",
    str(root / "agent/scripts/compose.integration.yaml"),
    "--profile",
    "development",
]

if not (root / ".env").is_file():
    subprocess.run([sys.executable, str(root / "scripts/init-local.py")], cwd=root, check=True)


def run(args):
    subprocess.run(compose + args, cwd=root, check=True)


run(["config", "--quiet"])
run(["up", "-d", "--build", "--wait", "--wait-timeout", "180"])
run(["exec", "-T", "backend", "flask", "--app", "wsgi", "seed-catalogs"])
if not fixtures.is_file():
    # Existing users without the credential fixture fail here deliberately; do not reset them.
    run(["exec", "-T", "backend", "flask", "--app", "wsgi", "seed-test-users"])
    fixtures.parent.mkdir(parents=True, exist_ok=True)
    run(["cp", "backend:/home/appuser/.test-users.json", str(fixtures)])
    from gianna.runtime.observability import private_directory

    private_directory(fixtures.parent)
print(
    "Gianna test stack ready: API 5400, web 5473, TV 5474, SMTP inbox 8027. Fixture credentials stay local."
)
