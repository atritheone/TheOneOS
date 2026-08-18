#!/usr/bin/env python3
"""Security-contract tests for the native T1OS system package manager.

Wheel imports use authenticated SCM_RIGHTS descriptors. Lock imports use a
bounded stream after the manager-ready handshake; caller path strings never
cross the privileged manager boundary. These tests exercise that public
dispatcher contract without importing T1OS code on the host.
"""

from __future__ import annotations

import ast
import array
import base64
import hashlib
import importlib
import importlib.util
import os
from pathlib import Path
import json
import socket
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
            "restore_modules", "clear_cache", "install_wheel", "apply_lock",
        }
        assert set(manager.READ_OPERATIONS) == expected_reads
        assert set(manager.MUTATION_OPERATIONS) == expected_mutations
        assert set(manager.DESCRIPTOR_OPERATIONS) == {"install_wheel", "apply_lock"}
        assert set(manager.OPERATIONS) == expected_reads | expected_mutations
        assert not any(name.startswith("pip_") for name in manager.OPERATIONS)
        assert manager.manager_python_command() == [os.path.realpath(sys.executable)]

        class FakeDistribution:
            def __init__(self, top_level, files):
                self.top_level = top_level
                self.files = files

            def read_text(self, name):
                return self.top_level if name == "top_level.txt" else None

        assert manager.distribution_imports(FakeDistribution(
            "_sodium\nnacl\n",
            ["nacl/__init__.py", "nacl/_sodium.abi3.so"],
        )) == ["nacl"]
        assert manager.distribution_imports(FakeDistribution(
            "_cffi_backend\ncffi\n",
            ["_cffi_backend.cpython-314-x86_64-linux-gnu.so", "cffi/__init__.py"],
        )) == ["_cffi_backend", "cffi"]

        # Keep recvmsg's control buffer below the VM kernel's ancillary-memory
        # ceiling while leaving room for credentials/security metadata plus a
        # descriptor.  An oversized request can be clipped to MSG_CTRUNC.
        receive_source = function_source(manager_path, "receive_request")
        assert "socket.CMSG_SPACE(4 * 1024)" in receive_source
        assert "socket.CMSG_SPACE(64 * 1024)" not in receive_source
        assert "tempfile.TemporaryFile" in receive_source
        assert "descriptors.append(os.dup(stream.fileno()))" in receive_source
        apply_source = function_source(manager_path, "op_apply_lock")
        assert "allow_anonymous=True" in apply_source
        request_source = function_source(manager_path, "request")
        serve_source = function_source(manager_path, "serve")
        assert "ready = channel.recv(1)" in request_source
        assert "channel.sendall(PROTOCOL_READY)" in serve_source
        assert serve_source.index("channel.setsockopt") < serve_source.index(
            "channel.sendall(PROTOCOL_READY)"
        )

        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        received_descriptors = []
        try:
            left.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
            with tempfile.TemporaryFile() as stream:
                stream.write(b"x")
                stream.flush()
                stream.seek(0)
                payload = (
                    json.dumps(request(manager, "apply_lock", {
                        "size": 1, "sha256": "a" * 64,
                    }), separators=(",", ":")) + "\n"
                ).encode("utf-8")
                rights = array.array("i", [stream.fileno()])
                right.sendmsg([payload], [(
                    socket.SOL_SOCKET, socket.SCM_RIGHTS, rights,
                )])
                received_request, received_descriptors = manager.receive_request(left)
                assert received_request["operation"] == "apply_lock"
                assert len(received_descriptors) == 1
        finally:
            for descriptor in received_descriptors:
                os.close(descriptor)
            left.close()
            right.close()

        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        received_descriptors = []
        lock_content = b'[t1os]\nformat = 1\n'
        try:
            payload = (
                json.dumps(request(manager, "apply_lock", {
                    "size": len(lock_content),
                    "sha256": hashlib.sha256(lock_content).hexdigest(),
                }), separators=(",", ":")) + "\n"
            ).encode("utf-8")
            right.sendall(payload + lock_content)
            received_request, received_descriptors = manager.receive_request(left)
            assert received_request["operation"] == "apply_lock"
            assert len(received_descriptors) == 1
            assert os.read(received_descriptors[0], len(lock_content) + 1) == lock_content
        finally:
            for descriptor in received_descriptors:
                os.close(descriptor)
            left.close()
            right.close()

        manager_source = Path(manager_path).read_text(encoding="utf-8")
        for retired_authority in (
            "role=architect", "currentrole", "T1OS_ARCHITECT_TOKEN", "master.txt",
        ):
            assert retired_authority not in manager_source

        operations_server_path = (
            Path(manager_path).parent.parent / "operations" / "operationsserver.py"
        )
        brick_path = Path(manager_path).parent.parent / "brick" / "brick.py"
        brick_source = brick_path.read_text(encoding="utf-8")
        brick_tree = ast.parse(brick_source, filename=os.fspath(brick_path))
        python_directives = {}
        for node in ast.walk(brick_tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "makespec"
                and len(node.args) >= 2
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                continue
            category = next(
                (keyword.value.value for keyword in node.keywords
                 if keyword.arg == "category"
                 and isinstance(keyword.value, ast.Constant)),
                None,
            )
            if category != "python":
                continue
            assert isinstance(node.args[1], (ast.List, ast.Tuple))
            aliases = [
                item.value for item in node.args[1].elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            ]
            python_directives[node.args[0].value] = aliases
        assert len(python_directives) == 20, python_directives
        python_aliases = {
            "python status": "ps",
            "check python": "cp",
            "check python modules": "cpm",
            "python history": "ph",
            "list python modules": "lpm",
            "show python module": "spm",
            "find python module": "fpm",
            "list python updates": "lpu",
            "install python module": "ipm",
            "install python wheel": "ipw",
            "remove python module": "rpm",
            "update python module": "upm",
            "update python modules": "upms",
            "pin python module": "ppm",
            "unpin python module": "unpm",
            "repair python modules": "rprm",
            "restore python modules": "rspm",
            "clear python cache": "cpc",
            "export python lock": "epl",
            "apply python lock": "apl",
        }
        assert set(python_directives) == set(python_aliases)
        for directive, alias in python_aliases.items():
            assert alias in python_directives[directive], (
                directive, python_directives[directive]
            )
        missing_source = function_source(brick_path, "missingpythonmodules")
        prepare_source = function_source(brick_path, "preparepythonmodules")
        detector_namespace = {
            "os": os, "stat": __import__("stat"), "ast": ast,
            "importlib": importlib, "sys": sys,
        }
        exec(missing_source, detector_namespace)
        missing_script = Path(temporary) / "missing_import_test.py"
        missing_script.write_text(
            "import json\nimport t1os_module_that_is_not_installed\n",
            encoding="utf-8",
        )
        assert detector_namespace["missingpythonmodules"](
            os.fspath(missing_script)
        ) == ["t1os_module_that_is_not_installed"]
        assert "importlib.invalidate_caches()" in missing_source
        assert "install them? (yes/no)" in prepare_source
        assert "answer yes or no in lowercase" in prepare_source
        assert "if answer in ('yes', 'no')" in prepare_source
        assert "authorisedpythoncall" in prepare_source
        server_policy = function_source(
            operations_server_path, "pythoncapabilitypolicy"
        )
        for required_policy in (
            "'install_wheel': 'python:install-wheel'",
            "'apply_lock': 'python:apply-lock'",
        ):
            assert required_policy in server_policy

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

        for operation in sorted(manager.DESCRIPTOR_OPERATIONS):
            expect_manager_error(
                manager, "invalid_arguments",
                lambda operation=operation: manager.dispatch(
                    request(manager, operation), None),
            )

        policy_cases = {
            ("install_module", (("name", "Safe.Name"),)): (
                "python:install", "safe-name@latest"),
            ("install_module", (("name", "Safe.Name"), ("version", "1.2"))): (
                "python:install", "safe-name@1.2"),
            ("install_wheel", (
                ("filename", "safe_name-1.0-py3-none-any.whl"),
                ("size", 1234), ("sha256", "a" * 64),
            )): (
                "python:install-wheel",
                "safe_name-1.0-py3-none-any.whl@" + "a" * 64,
            ),
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
            ("apply_lock", (("size", 1234), ("sha256", "b" * 64))): (
                "python:apply-lock", "b" * 64),
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
                if operation in manager.DESCRIPTOR_OPERATIONS:
                    manager.OPERATIONS[operation] = (
                        lambda arguments, descriptor, operation=operation: {
                            "message": operation + " accepted by test boundary",
                            "descriptor": descriptor,
                        }
                    )
                else:
                    manager.OPERATIONS[operation] = (
                        lambda arguments, operation=operation: {
                            "message": operation + " accepted by test boundary",
                        }
                    )
            for operation in sorted(expected_mutations):
                authorizations.clear()
                descriptors = [7] if operation in manager.DESCRIPTOR_OPERATIONS else None
                manager.set_progress(operation, "testing", "test-transaction")
                response = manager.dispatch(
                    request(manager, operation, valid_arguments[operation]),
                    peer, descriptors,
                )
                assert response["ok"] is True
                assert manager.progress()["running"] is False
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
