from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _resolve_bash() -> str:
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


class SchedulerStandaloneContractTests(unittest.TestCase):
    def test_scheduler_app_entry_exists_and_disables_web_autostart(self):
        source = _read("scheduler_app.py")
        self.assertIn("create_app(autostart_scheduler=False)", source)
        self.assertIn('os.environ["SCHEDULER_STANDALONE"] = "true"', source)
        self.assertIn('os.environ["SCHEDULER_PROCESS"] = "true"', source)
        self.assertIn("init_scheduler", source)
        self.assertIn("test_refresh_token_with_rotation", source)

    def test_config_exposes_scheduler_standalone_flag(self):
        from outlook_web import config

        with patch.dict(os.environ, {"SCHEDULER_STANDALONE": "true"}, clear=False):
            self.assertTrue(config.get_scheduler_standalone())
        with patch.dict(os.environ, {"SCHEDULER_STANDALONE": "false"}, clear=False):
            self.assertFalse(config.get_scheduler_standalone())

    def test_should_autostart_false_for_web_when_standalone(self):
        from outlook_web.services import scheduler as scheduler_service

        env = {
            "SCHEDULER_STANDALONE": "true",
            "SCHEDULER_AUTOSTART": "true",
        }
        env.pop("SCHEDULER_PROCESS", None)
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("SCHEDULER_PROCESS", None)
            self.assertFalse(scheduler_service.should_autostart_scheduler())

    def test_should_autostart_true_for_scheduler_process_when_enabled(self):
        from outlook_web.services import scheduler as scheduler_service

        with patch.dict(
            os.environ,
            {
                "SCHEDULER_STANDALONE": "true",
                "SCHEDULER_AUTOSTART": "true",
                "SCHEDULER_PROCESS": "true",
                "FLASK_RUN_FROM_CLI": "false",
            },
            clear=False,
        ):
            self.assertTrue(scheduler_service.should_autostart_scheduler())

    def test_start_script_documents_and_branches_on_standalone(self):
        script = _read("scripts/start-gunicorn.sh")
        self.assertIn("SCHEDULER_STANDALONE:=true", script)
        self.assertIn("python scheduler_app.py", script)
        self.assertIn("export SCHEDULER_AUTOSTART=false", script)
        self.assertIn("web_outlook_app:app", script)

    def test_compose_and_env_example_expose_standalone_knob(self):
        compose = _read("docker-compose.yml")
        env_example = _read(".env.example")
        self.assertIn("SCHEDULER_STANDALONE", compose)
        self.assertIn("SCHEDULER_STANDALONE", env_example)

    def _run_start_script_with_fakes(self, extra_env=None):
        script = REPO_ROOT / "scripts/start-gunicorn.sh"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            args_file = tmp / "gunicorn.args"
            fake_gunicorn = tmp / "gunicorn"
            fake_gunicorn.write_text(
                "#!/bin/sh\n" 'printf \'%s\\n\' "$@" > "$GUNICORN_ARGS_FILE"\n' "exit 0\n",
                encoding="utf-8",
            )
            fake_gunicorn.chmod(0o755)

            fake_python = tmp / "python"
            python_marker = tmp / "scheduler.started"
            fake_python.write_text(
                "#!/bin/sh\n"
                'if [ "$1" = "scheduler_app.py" ]; then\n'
                '  printf started > "$SCHEDULER_MARKER"\n'
                "  # Exit immediately: parent only needs the marker + PID bookkeeping.\n"
                "  exit 0\n"
                "fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)

            env = os.environ.copy()
            path_prefix = str(tmp).replace("\\", "/")
            env.update(
                {
                    "PATH": f"{path_prefix}:{env.get('PATH', '')}",
                    "GUNICORN_ARGS_FILE": str(args_file).replace("\\", "/"),
                    "SCHEDULER_MARKER": str(python_marker).replace("\\", "/"),
                }
            )
            if extra_env:
                env.update(extra_env)
            result = subprocess.run(
                [_resolve_bash(), str(script)],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
                timeout=15,
            )
            args = args_file.read_text(encoding="utf-8").splitlines() if args_file.exists() else []
            marker = python_marker.read_text(encoding="utf-8") if python_marker.exists() else ""
            return result, args, marker

    def test_start_script_legacy_mode_does_not_spawn_scheduler(self):
        result, args, marker = self._run_start_script_with_fakes({"SCHEDULER_STANDALONE": "false"})
        combined = f"{result.stdout or ''}{result.stderr or ''}"
        self.assertEqual(result.returncode, 0, combined)
        self.assertEqual(marker, "")
        self.assertIn("web_outlook_app:app", args)

    def test_start_script_default_mode_spawns_standalone_scheduler(self):
        result, args, marker = self._run_start_script_with_fakes({})
        combined = f"{result.stdout or ''}{result.stderr or ''}"
        self.assertEqual(result.returncode, 0, combined)
        self.assertEqual(marker, "started")
        self.assertEqual(args[0:2], ["-w", "2"])
        self.assertIn("web_outlook_app:app", args)
        self.assertIn("Started standalone scheduler", combined)

    def test_start_script_standalone_mode_spawns_scheduler_and_disables_autostart(self):
        result, args, marker = self._run_start_script_with_fakes(
            {
                "SCHEDULER_STANDALONE": "true",
                "GUNICORN_WORKERS": "2",
            }
        )
        combined = f"{result.stdout or ''}{result.stderr or ''}"
        self.assertEqual(result.returncode, 0, combined)
        self.assertEqual(marker, "started")
        self.assertEqual(args[0:2], ["-w", "2"])
        self.assertIn("web_outlook_app:app", args)
        self.assertIn("Started standalone scheduler", combined)


if __name__ == "__main__":
    unittest.main()
