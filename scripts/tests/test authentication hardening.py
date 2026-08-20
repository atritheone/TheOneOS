#!/usr/bin/env python3
"""Focused authentication, authorization, and credential-storage tests."""

import sys as _t1os_incremental_sys
from pathlib import Path as _T1OSIncrementalPath

if __name__ == "__main__":
    _t1os_incremental_scripts = next(
        (parent for parent in _T1OSIncrementalPath(__file__).resolve().parents
         if (parent / "incremental_test.py").is_file()),
        None,
    )
    if _t1os_incremental_scripts is not None:
        _t1os_incremental_sys.path.insert(0, str(_t1os_incremental_scripts))
        from _incremental_test import guard as _t1os_incremental_guard
        if _t1os_incremental_guard(__file__, _t1os_incremental_sys.argv[1:]):
            raise SystemExit(0)

import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest


if os.name != "posix":
    raise SystemExit(
        "refusing to import T1OS runtime code outside an isolated Linux environment"
    )

sys.dont_write_bytecode = True


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILD_ROOT = PROJECT_ROOT / "source" / "build software"
BROKER_PATH = BUILD_ROOT / "broker" / "broker.py"
ARCHITECT_PATH = BUILD_ROOT / "architect" / "architect.py"
STARTUP_PATH = BUILD_ROOT / "startup" / "startup.py"
RECOVERY_PATH = PROJECT_ROOT / "source" / "entry" / "init" / "angel recovery.sh"
INIT_PATH = PROJECT_ROOT / "source" / "entry" / "init" / "init hardware.sh"
DEPLOYMENT_PATH = PROJECT_ROOT / "scripts" / "deployment"
DISK_USER_PATH = DEPLOYMENT_PATH / "create disk user.ps1"


def load_module(name, path):
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


broker = load_module("t1os_auth_test_broker", BROKER_PATH)


class BrokerTests(unittest.TestCase):
    password = "correct horse battery staple"

    def test_password_creation_range_is_four_to_thirty_two_characters(self):
        self.assertEqual(broker.MIN_NEW_PASSWORD_CHARS, 4)
        self.assertEqual(broker.MAX_PASSWORD_CHARS, 32)
        self.assertEqual(broker.MAX_PASSWORD_BYTES, 128)
        self.assertEqual(broker.validate_new_password("a" * 4), 4)
        self.assertEqual(broker.validate_new_password("a" * 32), 32)
        self.assertEqual(broker.validate_new_password("\U0001f600" * 32), 128)
        for invalid in ("a" * 3, "a" * 33, "four\x00"):
            with self.subTest(length=len(invalid)):
                with self.assertRaises(ValueError):
                    broker.validate_new_password(invalid)

    def test_hash_verification_and_bounded_formats(self):
        stored = broker.hash_password(self.password)
        expected = "kdf=argon2id" if broker.argon2id_available() else "kdf=scrypt"
        self.assertIn(expected, stored)
        self.assertTrue(broker.verify_password(self.password, stored))
        self.assertFalse(broker.verify_password("not the password", stored))

        fields = stored.split("$")
        if "kdf=argon2id" in stored:
            fields[3] = "m=999999999"
        else:
            fields[3] = "n=999999999"
        self.assertFalse(broker.verify_password(self.password, "$".join(fields)))

    def test_versioned_scrypt_fallback_is_bounded(self):
        attempted = broker._ARGON2_LOAD_ATTEMPTED
        library = broker._ARGON2_LIBRARY
        try:
            broker._ARGON2_LOAD_ATTEMPTED = True
            broker._ARGON2_LIBRARY = None
            stored = broker.hash_password(self.password)
            self.assertIn("$v=1$kdf=scrypt$n=32768$r=8$p=1$", stored)
            self.assertTrue(broker.verify_password(self.password, stored))
        finally:
            broker._ARGON2_LOAD_ATTEMPTED = attempted
            broker._ARGON2_LIBRARY = library

    @unittest.skipUnless(os.name == "posix", "descriptor-relative test requires POSIX")
    def test_legacy_migration_and_atomic_0600_write(self):
        salt = bytes(range(16))
        digest = hashlib.pbkdf2_hmac(
            "sha256", self.password.encode(), salt, 100000, dklen=32
        )
        legacy = f"sha256$100000${salt.hex()}${digest.hex()}"
        with tempfile.TemporaryDirectory() as temporary:
            master = os.path.join(temporary, "master", "master.txt")
            rate = os.path.join(temporary, "authentication", "attempts.json")
            broker.atomic_write_credentials(master, "Alice", legacy)
            result = broker.authenticate_master(
                master, self.password, rate_path=rate, now=1000
            )
            self.assertTrue(result.ok)
            self.assertTrue(result.migrated)
            _, migrated = broker.read_credentials(master)
            self.assertTrue(migrated.startswith("t1auth$v=1$"))
            self.assertEqual(stat.S_IMODE(os.stat(master).st_mode), 0o600)
            self.assertEqual(
                stat.S_IMODE(os.stat(os.path.dirname(master)).st_mode), 0o700
            )

    def test_safe_username_canonicalization(self):
        self.assertEqual(broker.canonicalize_username("  Alice-1  "), "Alice-1")
        self.assertEqual(broker.canonicalize_username("Ａlice"), "Alice")
        for unsafe in ("", ".", "..", "../alice", "alice/bob", "alice\\bob", "a b"):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(ValueError):
                    broker.canonicalize_username(unsafe)

    @unittest.skipUnless(os.name == "posix", "descriptor-relative test requires POSIX")
    def test_symlinked_home_and_credential_targets_do_not_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = os.path.join(temporary, "home")
            outside = os.path.join(temporary, "outside")
            os.mkdir(home)
            os.mkdir(outside)
            os.symlink(outside, os.path.join(home, "Alice"))
            with self.assertRaises(OSError):
                broker.ensure_user_tree(home, "Alice")
            self.assertEqual(os.listdir(outside), [])

            master_directory = os.path.join(temporary, "credentials")
            os.mkdir(master_directory)
            os.chmod(master_directory, 0o700)
            outside_file = os.path.join(temporary, "outside.txt")
            Path(outside_file).write_text("unchanged", encoding="utf-8")
            os.symlink(outside_file, os.path.join(master_directory, "master.txt"))
            stored = broker.hash_password(self.password)
            broker.atomic_write_credentials(
                os.path.join(master_directory, "master.txt"), "Alice", stored
            )
            self.assertEqual(Path(outside_file).read_text(encoding="utf-8"), "unchanged")
            self.assertFalse(os.path.islink(os.path.join(master_directory, "master.txt")))

    @unittest.skipUnless(os.name == "posix", "persistent limiter test requires POSIX")
    def test_rate_limit_and_backoff(self):
        with tempfile.TemporaryDirectory() as temporary:
            master = os.path.join(temporary, "master", "master.txt")
            rate = os.path.join(temporary, "authentication", "attempts.json")
            broker.atomic_write_credentials(
                master, "Alice", broker.hash_password(self.password)
            )
            first = broker.authenticate_master(
                master, "incorrect", rate_path=rate, now=1000
            )
            self.assertFalse(first.ok)
            self.assertEqual(first.retry_after, 1.0)
            blocked = broker.authenticate_master(
                master, self.password, rate_path=rate, now=1000.5
            )
            self.assertEqual(blocked.error, "rate-limited")
            allowed = broker.authenticate_master(
                master, self.password, rate_path=rate, now=1001.1
            )
            self.assertTrue(allowed.ok)
            self.assertEqual(stat.S_IMODE(os.stat(rate).st_mode), 0o600)

    def test_ambient_architect_bearer_api_is_absent(self):
        for name in (
            "issue_authorization", "validate_authorization",
            "revoke_authorization", "authenticate_and_issue",
            "AUTHORIZATION_ENVIRONMENT",
        ):
            self.assertFalse(hasattr(broker, name), name)

    @unittest.skipUnless(os.name == "posix", "recovery record test requires POSIX")
    def test_action_scoped_recovery_authorization(self):
        with tempfile.TemporaryDirectory() as temporary:
            master = os.path.join(temporary, "master", "master.txt")
            rate = os.path.join(temporary, "authentication", "attempts.json")
            broker.atomic_write_credentials(
                master, "Alice", broker.hash_password(self.password)
            )
            issued = broker.issue_recovery_authorization(
                master, self.password, "reinstall", ttl=300, rate_path=rate
            )
            self.assertTrue(issued.authentication.ok)
            self.assertEqual(len(issued.token), 43)
            self.assertTrue(broker.validate_recovery_authorization(
                master, issued.token, "reinstall"
            ))
            self.assertFalse(broker.validate_recovery_authorization(
                master, issued.token, "reset"
            ))
            digest = broker.recovery_authorization_digest(
                master, issued.token, "reinstall",
                origin_boot_id="12345678-1234-4234-9234-123456789abc",
            )
            record = os.path.join(
                os.path.dirname(master), "recovery authorizations", digest
            )
            self.assertEqual(stat.S_IMODE(os.stat(record).st_mode), 0o600)
            contents = Path(record).read_text(encoding="ascii").splitlines()
            self.assertEqual(contents[0], "format=2")
            self.assertIn(
                "origin_boot_id=12345678-1234-4234-9234-123456789abc",
                contents,
            )

    def test_service_secret_store_is_narrow_and_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            broker.store_service_secret("wifi.test", b"secret", directory=temporary)
            self.assertEqual(
                broker.load_service_secret("wifi.test", directory=temporary), b"secret"
            )
            if os.name == "posix":
                self.assertEqual(
                    stat.S_IMODE(os.stat(os.path.join(temporary, "wifi.test.secret")).st_mode),
                    0o600,
                )
            with self.assertRaises(ValueError):
                broker.store_service_secret("../wifi", b"secret", directory=temporary)
            broker.delete_service_secret("wifi.test", directory=temporary)
            self.assertFalse(os.path.exists(os.path.join(temporary, "wifi.test.secret")))

    @unittest.skipUnless(os.name == "posix", "provisioning test requires POSIX")
    def test_provision_user_uses_safe_tree_and_private_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            username = broker.provision_user(temporary, "Alice", self.password)
            self.assertEqual(username, "Alice")
            master = os.path.join(temporary, "the one", "master", "master.txt")
            self.assertEqual(stat.S_IMODE(os.stat(master).st_mode), 0o600)
            self.assertTrue(broker.verify_password(
                self.password, broker.read_credentials(master)[1]
            ))
            for relative in (
                ("flash", "books"), ("flash", "music"),
                ("flash", "images"), ("flash", "downloads"),
                ("flash", "videos"), ("expanse",),
                ("reference", "identity"),
            ):
                path = os.path.join(temporary, "master", "Alice", *relative)
                self.assertTrue(os.path.isdir(path))
                self.assertEqual(os.stat(path).st_uid, 1000)
                self.assertEqual(os.stat(path).st_gid, 1000)
                self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o700)

    @unittest.skipUnless(os.name == "posix", "account change test requires POSIX")
    def test_change_user_renames_home_and_uses_current_password_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            broker.provision_user(
                temporary, "Alice", self.password,
                owner_uid=os.getuid(), owner_gid=os.getgid(),
            )
            master = os.path.join(temporary, "the one", "master", "master.txt")
            original_hash = broker.read_credentials(master)[1]

            with self.assertRaises(broker.AuthenticationError):
                broker.change_user(temporary, "wrong", "Bob")
            self.assertTrue(os.path.isdir(os.path.join(temporary, "master", "Alice")))

            result = broker.change_user(temporary, self.password, "Bob")
            self.assertEqual(result["old_username"], "Alice")
            self.assertEqual(result["username"], "Bob")
            self.assertFalse(result["password_changed"])
            self.assertFalse(os.path.lexists(os.path.join(temporary, "master", "Alice")))
            self.assertTrue(os.path.isdir(os.path.join(temporary, "master", "Bob")))
            self.assertEqual(broker.read_credentials(master), ("Bob", original_hash))

            new_password = "the new secure password"
            result = broker.change_user(
                temporary, self.password, "Bob", new_password,
            )
            self.assertTrue(result["password_changed"])
            username, replacement = broker.read_credentials(master)
            self.assertEqual(username, "Bob")
            self.assertTrue(replacement.startswith("t1auth$v=1$"))
            self.assertTrue(broker.verify_password(new_password, replacement))
            self.assertFalse(broker.verify_password(self.password, replacement))

    @unittest.skipUnless(os.name == "posix", "account removal test requires POSIX")
    def test_remove_user_requires_both_factors_and_deletes_private_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            broker.provision_user(
                temporary, "Alice", self.password,
                owner_uid=os.getuid(), owner_gid=os.getgid(),
            )
            master = os.path.join(temporary, "the one", "master", "master.txt")
            home = os.path.join(temporary, "master", "Alice")
            marker = os.path.join(home, "reference", "identity", "marker")
            with open(marker, "w", encoding="utf-8") as stream:
                stream.write("private\n")

            with self.assertRaises(broker.AuthenticationError):
                broker.remove_user(temporary, self.password, "NotAlice")
            with self.assertRaises(broker.AuthenticationError):
                broker.remove_user(temporary, "wrong", "Alice")
            self.assertTrue(os.path.isfile(master))
            self.assertTrue(os.path.isfile(marker))

            self.assertEqual(
                broker.remove_user(temporary, self.password, "Alice"), "Alice"
            )
            self.assertFalse(os.path.lexists(master))
            self.assertFalse(os.path.lexists(home))
            self.assertFalse(any(
                name.startswith(".removed-")
                for name in os.listdir(os.path.join(temporary, "master"))
            ))


@unittest.skipUnless(os.name == "posix", "Architect integration test requires POSIX")
class ArchitectTests(unittest.TestCase):
    def test_mutable_role_cannot_bypass_protected_paths(self):
        architect = load_module("t1os_architect_test", ARCHITECT_PATH)
        architect.currentrole = "architect"
        self.assertEqual(architect.loadrole(), "master")
        self.assertFalse(architect.check("/the one/build/anything"))
        self.assertFalse(architect.changeroleprocess("architect", "unused"))
        self.assertTrue(architect.saverole("master"))


class SourcePolicyTests(unittest.TestCase):
    def test_sources_compile_and_recovery_gates_precede_actions(self):
        for path in (BROKER_PATH, ARCHITECT_PATH, STARTUP_PATH):
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        recovery = RECOVERY_PATH.read_text(encoding="utf-8")
        runner = recovery[recovery.index("angel_run_action()") :]
        self.assertLess(
            runner.index('angel_require_recovery_authorization "$action"'),
            runner.index('case "$action" in'),
        )
        init = INIT_PATH.read_text(encoding="utf-8")
        self.assertIn(
            'if [ "$debug" = 1 ] && [ "$developer" = 1 ]; then', init
        )
        self.assertIn("t1os.developer=1) developer_request=1", init)
        self.assertIn("[ -f /t1os-developer-policy ]", init)
        self.assertIn("= enabled ]; then", init)
        disk_user = DISK_USER_PATH.read_text(encoding="utf-8")
        self.assertIn("provision-user", disk_user)
        self.assertIn("$password.Length -lt 4", disk_user)
        self.assertIn("$password.Length -gt 32", disk_user)
        self.assertNotIn("between 12 and 256", disk_user)
        self.assertNotIn("Rfc2898DeriveBytes", disk_user)
        self.assertNotIn("chmod 0644", disk_user)
        self.assertIn("$passwordInput = $password", disk_user)
        self.assertIn("[switch]$UsbDrive", disk_user)
        self.assertIn("change-user", (
            DEPLOYMENT_PATH / "change disk user.ps1"
        ).read_text(encoding="utf-8"))
        self.assertIn("remove-user", (
            DEPLOYMENT_PATH / "remove disk user.ps1"
        ).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
