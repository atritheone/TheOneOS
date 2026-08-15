from pathlib import Path
import json
import os
import sys
import tempfile


def main():
    project = Path(sys.argv[1]).resolve()
    agent_path = project / "source/software/virtualbox/vmtestagent.py"
    namespace = {}
    exec(compile(agent_path.read_text(encoding="utf-8"), str(agent_path), "exec"), namespace)

    calls = []

    def broker(payload, timeout=180):
        calls.append((dict(payload), timeout))
        if payload["action"] == "VM_TEST_BRICK_EXECUTE":
            directive = payload["directive"]
            timed_out = directive == "timeout"
            passed = directive != "fail" and not timed_out
            result = {"format": 1, "passed": passed, "command": directive}
            return {
                "status": "ok",
                "passed": passed,
                "exit_code": 0 if passed else 1,
                "timed_out": timed_out,
                "source": "deployed",
                "brick_path": "/the one/build/brick/brick.py",
                "result": result,
                "stdout": json.dumps(result) + "\n",
                "stderr": "",
                "stdout_truncated": False,
                "stderr_truncated": False,
            }
        if payload["action"] == "VM_TEST_LAUNCH":
            application = payload["application"]
            return {
                "status": "ok",
                "passed": True,
                "pid": os.getpid(),
                "profile": {"brick": "brick", "settings": "settings", "player": "video"}[application],
                "application_path": f"/the one/build/{application}/{application}.py",
                "media_path": namespace["PLAYER_MEDIA_PATH"] if application == "player" else None,
                "source": "deployed",
            }
        if payload["action"] == "VM_TEST_STATUS":
            return {
                "status": "ok",
                "source": "broker-owned-guest-state",
                "has_user": True,
                "username": "TestUser",
                "session_active": True,
                "exchange_ready": True,
                "windowserver_ready": True,
                "lock_screen_ready": True,
                "terminal_fixture_result": "TERMINAL_EMULATOR_PASS\n",
                "player_status": {
                    "pid": os.getpid(),
                    "media_path": namespace["PLAYER_MEDIA_PATH"],
                    "media_kind": "video",
                    "state": "playing",
                    "position": 2.5,
                    "duration": 60.0,
                    "error": "",
                    "frame_ready": True,
                    "frame_width": 1280,
                    "frame_height": 720,
                    "frame_number": 75,
                },
                "media_runtime": {
                    "directory": True, "uid": 1000, "gid": 1000, "mode": "0700",
                },
                "applications": {
                    "brick": True, "settings": True, "player": True,
                },
            }
        raise AssertionError(payload)

    namespace["_operations_request"] = broker

    with tempfile.TemporaryDirectory(prefix="t1os-vm-agent-") as temporary:
        root = Path(temporary)
        media = root / "without_a_blush.mp4"
        media.write_bytes(b"fixture")
        namespace["PLAYER_MEDIA_PATH"] = str(media)

        exchange = root / "exchange"
        exchange.mkdir()
        namespace["write_ready"](str(exchange), source_build=str(root / "ignored"))
        ready = json.loads((exchange / "agent-ready.json").read_text(encoding="utf-8"))
        assert ready["source"] == "deployed"
        assert ready["brick_path"] == "/the one/build/brick/brick.py"

        request_id = "a" * 12
        request = {
            "format": 1,
            "id": request_id,
            "action": "brick",
            "directive": "version; role",
            "timeout_seconds": 10,
        }
        request_path = exchange / f"request-{request_id}.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        assert namespace["process_requests"](str(exchange)) == 1
        response = json.loads(
            (exchange / f"response-{request_id}.json").read_text(encoding="utf-8")
        )
        assert response["passed"] is True
        assert response["source"] == "deployed"
        assert response["result"]["command"] == "version; role"
        assert not request_path.exists()

        failed = namespace["execute"]({"directive": "fail", "timeout_seconds": 10})
        assert failed["passed"] is False and failed["exit_code"] == 1
        timed_out = namespace["execute"]({"directive": "timeout", "timeout_seconds": 1})
        assert timed_out["passed"] is False and timed_out["timed_out"] is True

        gui_id = "c" * 12
        gui_path = exchange / f"request-{gui_id}.json"
        gui_path.write_text(json.dumps({
            "format": 1, "id": gui_id, "action": "brick-gui",
        }), encoding="utf-8")
        assert namespace["process_requests"](str(exchange)) == 1
        gui = json.loads(
            (exchange / f"response-{gui_id}.json").read_text(encoding="utf-8")
        )
        assert gui["passed"] is True
        assert gui["action"] == "brick-gui"
        assert gui["source"] == "deployed"
        assert gui["pid"] == os.getpid()

        settings = namespace["launch_fixed_gui"]("settings-gui")
        assert settings["passed"] is True and settings["source"] == "deployed"
        player = namespace["launch_fixed_gui"]("player-gui")
        assert player["passed"] is True and player["media_path"] == str(media)

        if os.name == "nt":
            namespace["FIXED_PROCESSES"].clear()
        features = namespace["feature_status"]()
        assert features["passed"] is True
        assert features["terminal_fixture_passed"] is True
        if os.name != "nt":
            assert features["player_alive"] is True
        assert features["player_media_bytes"] == len(b"fixture")
        assert features["player_playback_ready"] is True
        assert features["player_status"]["frame_width"] == 1280
        assert features["media_runtime"]["mode"] == "0700"

        status = namespace["session_status"]()
        assert status["passed"] is True
        assert status["has_user"] is True
        assert status["username"] == "TestUser"
        assert status["session_active"] is True
        assert status["exchange_ready"] is True
        assert status["windowserver_ready"] is True
        assert status["lock_screen_ready"] is True

        rejected_id = "b" * 12
        rejected_path = exchange / f"request-{rejected_id}.json"
        rejected_path.write_text(json.dumps({
            "format": 1,
            "id": rejected_id,
            "action": "shell",
            "directive": "anything",
        }), encoding="utf-8")
        assert namespace["process_requests"](str(exchange)) == 1
        rejected = json.loads(
            (exchange / f"response-{rejected_id}.json").read_text(encoding="utf-8")
        )
        assert rejected["passed"] is False
        assert "only fixed T1OS application and read-only session-status actions" in rejected["error"]

    assert any(call[0]["action"] == "VM_TEST_BRICK_EXECUTE" for call in calls)
    assert any(call[0]["action"] == "VM_TEST_LAUNCH" for call in calls)
    assert any(call[0]["action"] == "VM_TEST_STATUS" for call in calls)
    print("VM test agent validation passed.")


if __name__ == "__main__":
    main()
