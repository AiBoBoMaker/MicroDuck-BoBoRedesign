"""Reproduce v155 native HOME regressions with the host environment used to build them.

Usage: python run_native_home155.py
CARGO_TARGET_DIR is supplied by build152/env-host.json. Every executed filter
must match and run a nonzero number of tests. No robot hardware is accessed.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import time

BASE = Path(__file__).resolve().parent
SOURCE = BASE / "source/Microduck-Source-R17-v1.0.155"
ENV = {**os.environ, **json.loads((BASE / "build152/env-host.json").read_text())}
FILTERS = [
    "r17_explicit_disable_returns_home_only_after_an_enabled_policy",
    "explicit_home_after_a_policy_pause_restores_absolute_home_without_replay",
    "intents::tests::",
    "home_start::tests::",
    "r17_start_outside_home_requests_home_without_enabling",
    "r17_homed_flag_alone_cannot_enable_and_home_does_not_replay_the_press",
    "r17_old_home_feedback_cannot_enable",
    "r17_init_needs_no_home_imu_or_readiness_precheck",
    "start_home_ends_the_seat_even_when_reads_are_paused",
    "feetech_official_coast_holds_and_resumes_without_reenable",
    "faults_and_service_teardown_preserve_torque_explicit_relax_still_works",
    "a_restart_asks_for_no_torque",
    "enabling_without_a_policy_leaves_the_joints_limp",
    "robot_init_powers_the_joints_and_ramps_home",
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprints():
    paths = [SOURCE / "Cargo.lock", SOURCE / "Cargo.toml"]
    for folder in ("robotd", "duck-control", "robotd-params", "duck-ipc-proto", "kinematics", "odometry", "tof"):
        paths.extend((SOURCE / folder).rglob("*.rs"))
        paths.extend((SOURCE / folder).rglob("Cargo.toml"))
    return {str(p.relative_to(SOURCE)): sha(p) for p in sorted(set(paths))}


before = fingerprints()
began = time.monotonic()
results = []
build_command = ["cargo", "test", "-p", "robotd", "--bin", "robotd", "--frozen", "--no-run", "--message-format=json"]
with (BASE / "native-tests155-final.log").open("w") as log:
    log.write("BUILD COMMAND: " + " ".join(build_command) + "\n")
    log.flush()
    build = subprocess.run(build_command, cwd=SOURCE, env=ENV, stdout=subprocess.PIPE, stderr=log, text=True)
    if build.returncode:
        raise SystemExit(build.returncode)
    artifacts = [json.loads(line) for line in build.stdout.splitlines() if line.startswith("{")]
    candidates = [row["executable"] for row in artifacts if row.get("reason") == "compiler-artifact"
                  and row.get("executable") and row.get("target", {}).get("name") == "robotd"
                  and row.get("profile", {}).get("test")]
    assert len(candidates) == 1, candidates
    binary = BASE / "home155-final-test-bin"
    shutil.copy2(candidates[0], binary)
    listing = subprocess.check_output([binary, "--list"], env=ENV, text=True)
    for filter_name in FILTERS:
        matched = [line[:-6] for line in listing.splitlines() if line.endswith(": test") and filter_name in line]
        assert matched, filter_name
        command = [str(binary), filter_name, "--test-threads=1"]
        log.write(f"FILTER: {filter_name} ({len(matched)} actual tests)\n")
        log.flush()
        run = subprocess.run(command, cwd=SOURCE, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        log.write(run.stdout)
        log.flush()
        counts = re.findall(r"test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed;", run.stdout)
        assert counts, (filter_name, run.stdout)
        passed, failed = map(int, counts[-1])
        assert passed + failed == len(matched), (filter_name, counts, matched)
        result = dict(command=command, filter=filter_name, tests=matched, passed=passed, failed=failed, exit_code=run.returncode)
        results.append(result)
        print(json.dumps({k: v for k, v in result.items() if k not in ("tests", "command")}), flush=True)
        if run.returncode:
            break

after = fingerprints()
record = dict(build_command=build_command, commands=results, exit_code=results[-1]["exit_code"],
              passed=sum(r["passed"] for r in results), failed=sum(r["failed"] for r in results),
              elapsed_seconds=round(time.monotonic() - began, 3), source_sha256=before,
              source_sha256_before=before, source_sha256_after=after, source_sha256_unchanged=before == after,
              test_binary_sha256=sha(binary), hardware_tested=False, tests_compile_source=str(SOURCE),
              runner_sha256=sha(Path(__file__)),
              fault_injection="real IPC dispatch and control_loop with real ONNX policy; simulated motor I/O, 6-degree leg sag and missing telemetry; independent beak excluded from stance comparisons",
              red_baseline="native-home155-red-confirmed.log", red_baseline_record="native-home155-red-confirmed.json")
(BASE / "native-tests155-final.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps({k: v for k, v in record.items() if k not in ("commands", "source_sha256", "source_sha256_before", "source_sha256_after", "build_command")}), flush=True)
raise SystemExit(record["exit_code"])
