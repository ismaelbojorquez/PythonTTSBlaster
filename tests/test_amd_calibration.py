import json
import subprocess
import sys
import wave
from pathlib import Path

from amd_samples import signal, silence

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_amd.py"


def write_wav(path, pcm):
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        wav.writeframes(pcm)


def run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        capture_output=True, text=True, timeout=10,
    )


def test_batch_comparison_preserves_unknowns_and_reports_policy_errors(tmp_path):
    write_wav(tmp_path / "human.wav", signal(2800) + silence(1800))
    write_wav(tmp_path / "machine.wav", signal(800) + silence(1200) + signal(3000))
    write_wav(tmp_path / "silent-person.wav", silence(6500))
    manifest = tmp_path / "samples.csv"
    manifest.write_text(
        "wav,label\nhuman.wav,human\nmachine.wav,machine\nsilent-person.wav,human\n"
    )
    old = tmp_path / "old.toml"
    old.write_text('[amd]\nenabled=true\n[sip]\npassword="test-secret-not-in-report"\n')
    report = tmp_path / "report.json"
    result = run("--config", ROOT / "config.example.toml", "--manifest", manifest,
                 "--compare-config", old, "--report", report)
    assert result.returncode == 0, result.stderr
    data = json.loads(report.read_text())
    current, comparison = data["current"], data["comparison"]
    assert current["confusion"] == {
        "human": {"human": 1, "machine": 0, "unknown": 1},
        "machine": {"human": 0, "machine": 1, "unknown": 0},
    }
    assert current["accuracy_all_samples"] == 2 / 3
    assert current["humans_rejected_by_policy"] == 0
    assert current["machines_allowed_by_policy"] == 0
    assert comparison["confusion"]["human"]["machine"] == 1
    assert comparison["confusion"]["machine"]["human"] == 1
    assert "test-secret-not-in-report" not in result.stdout + report.read_text()
    assert report.stat().st_mode & 0o777 == 0o600
    assert "no se abrió la troncal" in result.stdout


def test_manifest_validation_and_report_never_overwrite_inputs(tmp_path):
    write_wav(tmp_path / "hello.wav", signal(400) + silence(1800))
    config = tmp_path / "config.toml"
    config.write_text('[amd]\nenabled=true\n')
    manifest = tmp_path / "samples.csv"
    for contents in (
        "wav,label\n", "wav,label\nhello.wav,guess\n",
        "wav,label\nhello.wav,human\n./hello.wav,human\n",
    ):
        manifest.write_text(contents)
        assert run("--config", config, "--manifest", manifest).returncode == 2
    manifest.write_text("wav,label\nhello.wav,human\n")
    before = config.read_bytes()
    assert run("--config", config, "--manifest", manifest,
               "--report", config).returncode == 2
    assert config.read_bytes() == before
