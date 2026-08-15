#!/usr/bin/env python3
"""Security-contract tests for the native T1OS system package manager.

Path-based wheel and lock installation is intentionally unavailable until the
manager has SCM_RIGHTS descriptor transport.  These tests exercise the public
dispatcher boundary without weakening that policy or importing T1OS runtime
code under the Windows host interpreter.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import importlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile


def expect_manager_error(manager, code, operation):
    try:
        operation()
    except manager.ManagerError as error:
        assert error.code == code, (error.code, code, str(error))
    else:
        raise AssertionError("operation unexpectedly succeeded")


def expect_value_error(operation):
    try:
        operation()
    except ValueError:
        return
    raise AssertionError("authorization policy unexpectedly accepted input")


def request(manager, operation, arguments=None):
    return {
        "format": manager.PROTOCOL,
        "operation": operation,
        "arguments": dict(arguments or {}),
    }


def function_source(path, name):
    source = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=os.fspath(path))
    node = next(
        item for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name == name
    )
    return ast.get_source_segment(source, node)


def main(argv):
    if len(argv) != 5:
        raise SystemExit("test_python_packages.py MANAGER LOADER PYTHON LIBRARY_PATH")
    manager_path = os.path.abspath(argv[1])
    # The remaining arguments are retained by this deployment test's stable
    # interface and prove that the canonical runtime payload was resolved by
    # the caller.  This test does not execute a second interpreter or loader.
    for required in map(os.path.abspath, argv[2:4]):
        assert os.path.isfile(required), required

    with tempfile.TemporaryDirectory(prefix="t1pip-security-", dir="/var/tmp") as temporary:
        root = os.path.join(temporary, "the one")
        management = os.path.join(root, "software", "python", ".t1pip")
        os.makedirs(management, mode=0o700)
        os.environ.update({
            "T1OS_SYSTEM_ROOT": root,
            "T1OS_PYTHON_MANAGEMENT_ROOT": management,
        })

        specification = importlib.util.spec_from_file_location("t1pip_tested", manager_path)
        manager = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(manager)
        operations_client = importlib.import_module("operations.operations")

        expected_reads = {
            "status", "list_modules", "show_module", "find_module",
            "list_updates", "check_modules", "history", "export_lock",
        }
        expected_mutations = {
            "install_module", "remove_module", "pin_module", "unpin_module",
            "update_module", "update_modules", "repair_modules",
            "restore_modules", "clear_cache",
        }
        expected_disabled = {"install_wheel", "apply_lock"}
        assert set(manager.READ_OPERATIONS) == expected_reads
        assert set(manager.MUTATION_OPERATIONS) == expected_mutations
        assert set(manager.DISABLED_DESCRIPTOR_OPERATIONS) == expected_disabled
        assert set(manager.OPERATIONS) == expected_reads | expected_mutations | expected_disabled
        assert not any(name.startswith("pip_") for name in manager.OPERATIONS)
        assert manager.manager_python_command() == [os.path.realpath(sys.executable)]

        manager_source = Path(manager_path).read_text(encoding="utf-8")
        for retired_authority in (
            "role=architect", "currentrole", "T1OS_ARCHITECT_TOKEN", "master.txt",
        ):
            assert retired_authority not in manager_source

        invalid_requests = (
            ("install_module", {"name": "safe-name", "path": "/tmp/hostile.whl"}),
            ("install_module", {"name": "safe-name", "pin": True}),
            ("install_module", {"name": "safe-name", "unknown": "value"}),
            ("remove_module", {}),
            ("remove_module", {"name": "safe-name", "version": "1"}),
            ("update_modules", {"name": "safe-name"}),
            ("repair_modules", {"path": "/tmp/lock"}),
            ("restore_modules", {"generation": "caller-selected"}),
            ("clear_cache", {"all": True}),
            ("history", {"limit": 10, "extra": True}),
            ("export_lock", {"path": "/tmp/pylock.toml"}),
            ("install_wheel", {"path": "/tmp/hostile.whl"}),
            ("apply_lock", {"path": "/tmp/hostile.toml"}),
        )
        for operation, arguments in invalid_requests:
            expect_manager_error(
                manager, "invalid_arguments",
                lambda operation=operation, arguments=arguments: manager.dispatch(
                    request(manager, operation, arguments), None),
            )

        for operation in sorted(expected_disabled):
            expect_manager_error(
                manager, "descriptor_transport_required",
                lambda operation=operation: manager.dispatch(
                    request(manager, operation), None),
            )
        expect_manager_error(
            manager, "descriptor_transport_required",
            lambda: manager.op_install_wheel({"path": "/tmp/hostile.whl"}),
        )
        expect_manager_error(
            manager, "descriptor_transport_required",
            lambda: manager.op_apply_lock({"path": "/tmp/hostile.toml"}),
        )

        policy_cases = {
            ("install_module", (("name", "Safe.Name"),)): (
                "python:install", "safe-name@latest"),
            ("install_module", (("name", "Safe.Name"), ("version", "1.2"))): (
                "python:install", "safe-name@1.2"),
            ("remove_module", (("name", "Safe.Name"),)): (
                "python:remove", "safe-name"),
            ("pin_module", (("name", "Safe.Name"),)): (
                "python:pin", "safe-name"),
            ("unpin_module", (("name", "Safe.Name"),)): (
                "python:unpin", "safe-name"),
            ("update_module", (("name", "Safe.Name"),)): (
                "python:update", "safe-name"),
            ("update_modules", ()): ("python:update", "*"),
            ("repair_modules", ()): ("python:repair", "current-lock"),
            ("restore_modules", ()): ("python:restore", "previous-generation"),
            ("clear_cache", ()): ("python:clear-cache", "unused"),
        }
        valid_arguments = {}
        for (operation, pairs), expected in policy_cases.items():
            arguments = dict(pairs)
            valid_arguments[operation] = arguments
            assert operations_client.python_authorization_policy(
                operation, arguments) == expected
        for arguments in (
            {"name": "safe-name", "path": "/tmp/hostile.whl"},
            {"name": "safe-name", "pin": True},
            {"name": "safe-name", "version": "1", "extra": True},
        ):
            expect_value_error(
                lambda arguments=arguments: operations_client.python_authorization_policy(
                    "install_module", arguments))

        peer = {
            "pid": 4100, "uid": 1000, "gid": 1000,
            "started": 9001, "domain": "brick",
        }
        authorizations = []

        def authorize(operation, arguments, **identity):
            authorizations.append((operation, dict(arguments), dict(identity)))
            return {"authorized": True}

        manager.architect_capability_check = authorize
        original_operations = dict(manager.OPERATIONS)
        try:
            for operation in expected_mutations:
                manager.OPERATIONS[operation] = (
                    lambda arguments, operation=operation: {
                        "message": operation + " accepted by test boundary",
                    }
                )
            for operation in sorted(expected_mutations):
                authorizations.clear()
                response = manager.dispatch(
                    request(manager, operation, valid_arguments[operation]), peer)
                assert response["ok"] is True
                assert len(authorizations) == 1
                authorised_operation, authorised_arguments, identity = authorizations[0]
                assert authorised_operation == operation
                assert authorised_arguments == valid_arguments[operation]
                assert identity == {
                    "client_pid": peer["pid"],
                    "client_started": peer["started"],
                    "client_uid": peer["uid"],
                    "timeout": 3.0,
                }

            manager.architect_capability_check = lambda *args, **kwargs: {
                "authorized": False,
            }
            expect_manager_error(
                manager, "architect_required",
                lambda: manager.dispatch(
                    request(manager, "clear_cache"), peer),
            )
        finally:
            manager.OPERATIONS.clear()
            manager.OPERATIONS.update(original_operations)

        exported = manager.dispatch(request(manager, "export_lock"), None)["data"]
        content = base64.b64decode(exported["content"], validate=True)
        assert len(content) <= 1024 * 1024
        assert exported["encoding"] == "base64"
        assert hashlib.sha256(content).hexdigest() == exported["sha256"]
        assert b"/tmp/" not in content

        operations_server = (
            Path(manager_path).parent.parent / "operations" / "operationsserver.py"
        )
        authorize_source = function_source(operations_server, "handlearchitectauthorize")
        check_source = function_source(operations_server, "handlearchitectcheck")
        assert "'uses': 1" in authorize_source
        assert "time.monotonic() + 60.0" in authorize_source
        consume = check_source.rfind("ARCHITECTCAPABILITIES.pop(key, None)")
        success = check_source.rfind("'authorized': True")
        assert consume >= 0 and success > consume
        assert "client_started" in check_source and "processstat" in check_source
        assert "subject['domain'] not in ('brick', 'settings')" in check_source

    print("python_package_security_contracts=pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
