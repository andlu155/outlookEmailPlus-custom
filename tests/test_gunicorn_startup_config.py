import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _resolve_bash() -> str:
    """Prefer Git Bash on Windows; plain `bash` is fine on Linux CI."""
    candidates = [
        os.environ.get("GIT_BASH"),
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        shutil.which("bash"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return "bash"


class GunicornStartupConfigTests(unittest.TestCase):
    def _run_start_script_with_fake_gunicorn(self, extra_env=None):
        script = REPO_ROOT / "scripts/start-gunicorn.sh"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            args_file = tmp / "gunicorn.args"
            fake_gunicorn = tmp / "gunicorn"
            fake_gunicorn.write_text(
                "#!/bin/sh\n" 'printf \'%s\\n\' "$@" > "$GUNICORN_ARGS_FILE"\n',
                encoding="utf-8",
            )
            fake_gunicorn.chmod(0o755)
            env = os.environ.copy()
            # Put the fake bin first using POSIX path style for Git Bash on Windows.
            path_prefix = str(tmp).replace("\\", "/")
            env.update(
                {
                    "PATH": f"{path_prefix}:{env.get('PATH', '')}",
                    "GUNICORN_ARGS_FILE": str(args_file).replace("\\", "/"),
                }
            )
            if extra_env:
                env.update(extra_env)
            # Invoke via bash so the shebang path works on Windows CI agents too.
            result = subprocess.run(
                [_resolve_bash(), str(script)],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
            )
            args = args_file.read_text(encoding="utf-8").splitlines() if args_file.exists() else []
            return result, args

    def test_dockerfile_uses_configurable_gunicorn_start_script(self):
        dockerfile = _read("Dockerfile")

        self.assertIn("GUNICORN_WORKERS=2", dockerfile)
        self.assertIn("GUNICORN_THREADS=8", dockerfile)
        self.assertIn("GUNICORN_TIMEOUT=120", dockerfile)
        self.assertIn("SCHEDULER_STANDALONE=true", dockerfile)
        self.assertIn('CMD ["scripts/start-gunicorn.sh"]', dockerfile)
        self.assertNotIn('CMD ["gunicorn", "-w", "1"', dockerfile)
        self.assertIn("chmod +x /app/scripts/start-gunicorn.sh", dockerfile)

    def test_compose_exposes_gunicorn_concurrency_knobs(self):
        compose = _read("docker-compose.yml")

        self.assertIn('GUNICORN_WORKERS: "${GUNICORN_WORKERS:-2}"', compose)
        self.assertIn('GUNICORN_THREADS: "${GUNICORN_THREADS:-8}"', compose)
        self.assertIn('GUNICORN_TIMEOUT: "${GUNICORN_TIMEOUT:-120}"', compose)
        self.assertIn('SCHEDULER_STANDALONE: "${SCHEDULER_STANDALONE:-true}"', compose)

    def test_start_script_keeps_multi_worker_default_with_standalone_scheduler(self):
        script = _read("scripts/start-gunicorn.sh")

        self.assertIn(': "${GUNICORN_WORKERS:=2}"', script)
        self.assertIn(': "${GUNICORN_THREADS:=8}"', script)
        self.assertIn(': "${GUNICORN_TIMEOUT:=120}"', script)
        self.assertIn(': "${SCHEDULER_STANDALONE:=true}"', script)
        self.assertIn("--threads", script)
        self.assertIn("web_outlook_app:app", script)
        self.assertNotIn("--preload", script)
        self.assertIn("wait-message", script)
        self.assertIn("SCHEDULER_STANDALONE", script)
        self.assertIn("scheduler_app.py", script)

    def test_start_script_passes_default_threaded_gunicorn_args(self):
        result, args = self._run_start_script_with_fake_gunicorn()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            args,
            [
                "-w",
                "2",
                "--threads",
                "8",
                "-b",
                "0.0.0.0:5000",
                "--timeout",
                "120",
                "--access-logfile",
                "-",
                "web_outlook_app:app",
            ],
        )

    def test_start_script_allows_env_overrides(self):
        result, args = self._run_start_script_with_fake_gunicorn(
            {
                "GUNICORN_WORKERS": "2",
                "GUNICORN_THREADS": "12",
                "GUNICORN_TIMEOUT": "90",
                "GUNICORN_BIND": "127.0.0.1:5050",
                "GUNICORN_ACCESS_LOGFILE": "/tmp/access.log",
            }
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            args,
            [
                "-w",
                "2",
                "--threads",
                "12",
                "-b",
                "127.0.0.1:5050",
                "--timeout",
                "90",
                "--access-logfile",
                "/tmp/access.log",
                "web_outlook_app:app",
            ],
        )

    def test_start_script_rejects_zero_or_non_numeric_values(self):
        script = REPO_ROOT / "scripts/start-gunicorn.sh"
        # Executable bit is enforced in Docker (chmod +x); on Windows the mode may not carry.
        if os.name != "nt":
            self.assertTrue(script.stat().st_mode & 0o111)

        result, _args = self._run_start_script_with_fake_gunicorn({"GUNICORN_THREADS": "0"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GUNICORN_THREADS must be a positive integer", result.stderr)

        result, _args = self._run_start_script_with_fake_gunicorn({"GUNICORN_WORKERS": "many"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GUNICORN_WORKERS must be a positive integer", result.stderr)


if __name__ == "__main__":
    unittest.main()
