import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy-production.sh"


def test_deploy_help_is_available():
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--dry-run" in result.stdout
    assert "--allow-local-backup" in result.stdout


@pytest.mark.parametrize("fail_stop", [False, True])
def test_deploy_dry_run_and_partial_stop_recovery(tmp_path: Path, fail_stop: bool):
    project = tmp_path / "project"
    fake_bin = tmp_path / "bin"
    project.mkdir()
    fake_bin.mkdir()

    for name in ("docker-compose.yml", ".env"):
        (project / name).write_text("services: {}\n")
    (project / ".gitignore").write_text("backups/\n")
    override = project / "compose.keep-db.json"
    override.write_text("{}\n")
    override.chmod(stat.S_IRUSR | stat.S_IWUSR)

    scripts = project / "scripts"
    scripts.mkdir()
    for name in ("backup-postgres.sh", "rehearse-postgres16.sh"):
        helper = scripts / name
        helper.write_text("#!/bin/sh\nexit 99\n")
        helper.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(
        ["git", "-C", str(project), "config", "user.email", "test@example.com"], check=True
    )
    subprocess.run(["git", "-C", str(project), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "fixture"], check=True)

    docker_log = tmp_path / "docker.log"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/bin/sh
printf '%s\\n' \"$*\" >>\"$DOCKER_LOG\"
case \" $* \" in
  *\" config --services \"*) printf 'db\\nmigrate\\nbot\\nwebapp\\n' ;;
  *\" config --quiet \"*) ;;
  *\" ps -q db \"*) printf 'database-id\\n' ;;
  *\" ps -q bot \"*) printf 'bot-id\\n' ;;
  *\" ps -q webapp \"*) printf 'webapp-id\\n' ;;
  *\" inspect --format {{.Image}} \"*) printf 'previous-image\\n' ;;
  *\" inspect --format \"*) printf 'healthy\\n' ;;
  *\" image tag \"*|*\" build migrate bot webapp \"*) ;;
  *\" stop bot webapp \"*) exit 42 ;;
  *\" start bot-id webapp-id \"*) ;;
  *) echo \"unexpected docker invocation: $*\" >&2; exit 90 ;;
esac
"""
    )
    fake_docker.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "PROJECT_DIR": str(project),
            "BACKUP_CONFIG": str(tmp_path / "missing-backup.conf"),
            "DOCKER_LOG": str(docker_log),
        }
    )
    result = subprocess.run(
        ["bash", str(SCRIPT), "--allow-local-backup"] + ([] if fail_stop else ["--dry-run"]),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    calls = docker_log.read_text()
    if fail_stop:
        assert result.returncode == 42, result.stderr
        assert "start bot-id webapp-id" in calls
        assert " run " not in calls
        assert " up " not in calls
        assert (
            "failed_utc="
            in next((project / "backups").glob("automatic/deploy-*/state")).read_text()
        )
        return
    assert result.returncode == 0, result.stderr
    assert "Dry-run only" in result.stdout
    for forbidden in (" build ", " stop ", " run ", " up ", " exec ", " image tag "):
        assert forbidden not in f" {calls} "
