#!/usr/bin/env python3
"""
SkillGod Vault Encryption — AES-256-GCM

License key + machine ID = 32-byte key via PBKDF2-SHA256.
Encrypted files (.sg) live in vault_encrypted/ — never in vault/.
Decryption happens in memory only; plaintext is never written to disk.

Requires: pip install cryptography
"""

import hashlib
import json
import os
import struct
import sys
from pathlib import Path

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    print("Install dependency: pip install cryptography")
    sys.exit(1)

ROOT            = Path(__file__).parent.parent
VAULT_DIR       = ROOT / "vault"
ENC_DIR         = ROOT / "vault_encrypted"
SENTINEL_NAME   = "_sentinel.sg"
PBKDF2_ITERS    = 200_000
SALT            = b"skillgod-vault-v1"   # public, non-secret salt
NONCE_LEN       = 12                     # GCM standard 96-bit nonce
TAG_LEN         = 16                     # GCM authentication tag
FILE_MAGIC      = b"SGv1"               # 4-byte file header


# ---------------------------------------------------------------------------
# Key derivation
# ---------------------------------------------------------------------------

def _derive_key(license_key: str, machine_id: str) -> bytes:
    """Derive a 32-byte AES key from license_key + machine_id via PBKDF2."""
    material = f"{license_key}:{machine_id}".encode("utf-8")
    return hashlib.pbkdf2_hmac(
        "sha256", material, SALT, PBKDF2_ITERS, dklen=32
    )


# ---------------------------------------------------------------------------
# Machine ID
# ---------------------------------------------------------------------------

def get_machine_id() -> str:
    """
    Return a stable hardware-based machine identifier.
    Windows: wmic csproduct get UUID
    Mac:     ioreg -rd1 -c IOPlatformExpertDevice
    Linux:   /etc/machine-id
    """
    import platform
    import subprocess

    system = platform.system()
    try:
        if system == "Windows":
            out = subprocess.check_output(
                ["wmic", "csproduct", "get", "UUID"],
                stderr=subprocess.DEVNULL, timeout=5
            ).decode().strip().splitlines()
            for line in out:
                line = line.strip()
                if line and line != "UUID" and "-" in line:
                    return line
        elif system == "Darwin":
            out = subprocess.check_output(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                stderr=subprocess.DEVNULL, timeout=5
            ).decode()
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    return line.split('"')[-2]
        else:  # Linux
            mid = Path("/etc/machine-id")
            if mid.exists():
                return mid.read_text().strip()
    except Exception:
        pass

    # Fallback: hostname hash
    import socket
    return hashlib.sha256(socket.gethostname().encode()).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Low-level encrypt / decrypt
# ---------------------------------------------------------------------------

def _encrypt_bytes(plaintext: bytes, key: bytes) -> bytes:
    """
    Encrypt plaintext with AES-256-GCM.
    Output format: MAGIC(4) | NONCE(12) | CIPHERTEXT+TAG
    """
    nonce = os.urandom(NONCE_LEN)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return FILE_MAGIC + nonce + ciphertext


def _decrypt_bytes(data: bytes, key: bytes) -> bytes:
    """
    Decrypt AES-256-GCM ciphertext.
    Raises ValueError on bad magic or authentication failure.
    """
    if len(data) < len(FILE_MAGIC) + NONCE_LEN + TAG_LEN:
        raise ValueError("File too short — not a valid .sg file")
    if data[:4] != FILE_MAGIC:
        raise ValueError(f"Invalid magic bytes: {data[:4]!r}")
    nonce      = data[4:4 + NONCE_LEN]
    ciphertext = data[4 + NONCE_LEN:]
    aesgcm     = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def encrypt_vault(license_key: str, machine_id: str = "") -> int:
    """
    Encrypt all vault/*.md files to vault_encrypted/*.sg.
    Creates a sentinel file for key verification.
    Returns count of encrypted files.
    """
    machine_id = machine_id or get_machine_id()
    key = _derive_key(license_key, machine_id)

    ENC_DIR.mkdir(parents=True, exist_ok=True)

    # Write sentinel (encrypts a known plaintext for fast key verification)
    sentinel_plain = b"skillgod-sentinel-ok"
    (ENC_DIR / SENTINEL_NAME).write_bytes(_encrypt_bytes(sentinel_plain, key))

    count = 0
    for md in VAULT_DIR.rglob("*.md"):
        rel      = md.relative_to(VAULT_DIR)
        out_path = ENC_DIR / rel.with_suffix(".sg")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        plaintext = md.read_bytes()
        out_path.write_bytes(_encrypt_bytes(plaintext, key))
        count += 1

    # Write manifest (unencrypted — just counts, no content)
    manifest = {
        "version":    "1.0",
        "skill_count": count,
        "license_key_prefix": license_key[:8] + "...",
        "machine_id_prefix":  machine_id[:8] + "...",
    }
    (ENC_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    print(f"Encrypted {count} skills -> {ENC_DIR}/")
    return count


def decrypt_skill(sg_file: Path, license_key: str,
                  machine_id: str = "") -> str:
    """
    Decrypt a single .sg file.
    Returns plaintext string — never writes to disk.
    Raises ValueError if key is wrong or file is corrupt.
    """
    machine_id = machine_id or get_machine_id()
    key  = _derive_key(license_key, machine_id)
    data = sg_file.read_bytes()
    return _decrypt_bytes(data, key).decode("utf-8")


def decrypt_all_to_memory(license_key: str,
                           machine_id: str = "") -> dict[str, str]:
    """
    Decrypt all .sg files in vault_encrypted/ to memory.
    Returns dict {relative_path: plaintext_content}.
    Never writes to disk.
    """
    machine_id = machine_id or get_machine_id()
    key    = _derive_key(license_key, machine_id)
    result = {}

    for sg in ENC_DIR.rglob("*.sg"):
        if sg.name == SENTINEL_NAME:
            continue
        rel = str(sg.relative_to(ENC_DIR).with_suffix(".md"))
        try:
            plaintext = _decrypt_bytes(sg.read_bytes(), key).decode("utf-8")
            result[rel] = plaintext
        except Exception:
            pass  # skip corrupt files

    return result


def verify_key(license_key: str, machine_id: str = "") -> bool:
    """
    Quick check: can this key decrypt the sentinel file?
    Returns True if key is valid for this vault_encrypted/ directory.
    """
    sentinel = ENC_DIR / SENTINEL_NAME
    if not sentinel.exists():
        return False
    machine_id = machine_id or get_machine_id()
    key = _derive_key(license_key, machine_id)
    try:
        plain = _decrypt_bytes(sentinel.read_bytes(), key)
        return plain == b"skillgod-sentinel-ok"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Vault sync (called by sg sync --key)
# ---------------------------------------------------------------------------

def sync_encrypted_vault(license_key: str, machine_id: str = "") -> int:
    """
    Decrypt vault_encrypted/*.sg → write to vault/ (in-place replace).
    This IS the sg sync --key full implementation.
    Returns count of skills written.
    """
    if not verify_key(license_key, machine_id):
        raise ValueError("Invalid license key or wrong machine ID")

    skills = decrypt_all_to_memory(license_key, machine_id)
    written = 0
    for rel_path, content in skills.items():
        dest = VAULT_DIR / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        written += 1
    return written


# ---------------------------------------------------------------------------
# Public convenience aliases for checkpoint tests and external callers
# ---------------------------------------------------------------------------

def derive_key(license_key: str, machine_id: str) -> bytes:
    """Public alias for _derive_key."""
    return _derive_key(license_key, machine_id)


def encrypt_skill(plaintext: str, key: bytes) -> bytes:
    """Encrypt a skill's plaintext content with a pre-derived key. Returns raw bytes."""
    return _encrypt_bytes(plaintext.encode("utf-8"), key)


# decrypt_skill already exists but takes a Path; add a bytes-accepting overload
_orig_decrypt_skill = decrypt_skill  # type: ignore[name-defined]


def decrypt_skill(source, license_key: str = "", machine_id: str = "",
                  key: bytes = None) -> str:
    """
    Decrypt a skill.
    - source=Path   → original file-based decrypt (license_key + machine_id)
    - source=bytes  → in-memory decrypt with pre-derived key
    """
    if isinstance(source, (bytes, bytearray)):
        if key is None:
            raise ValueError("key= required when source is bytes")
        return _decrypt_bytes(source, key).decode("utf-8")
    return _orig_decrypt_skill(source, license_key, machine_id)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="SkillGod vault encryption tool")
    sub = p.add_subparsers(dest="cmd")

    enc = sub.add_parser("encrypt", help="Encrypt vault/ → vault_encrypted/")
    enc.add_argument("--key", required=True, help="License key")
    enc.add_argument("--machine", default="", help="Override machine ID")

    dec = sub.add_parser("decrypt", help="Decrypt one .sg file (to stdout)")
    dec.add_argument("file", help="Path to .sg file")
    dec.add_argument("--key", required=True, help="License key")
    dec.add_argument("--machine", default="", help="Override machine ID")

    ver = sub.add_parser("verify", help="Verify key can decrypt sentinel")
    ver.add_argument("--key", required=True, help="License key")
    ver.add_argument("--machine", default="", help="Override machine ID")

    mid = sub.add_parser("machine-id", help="Print this machine's ID")

    args = p.parse_args()

    if args.cmd == "encrypt":
        mid = args.machine or get_machine_id()
        print(f"Machine ID : {mid[:16]}...")
        n = encrypt_vault(args.key, mid)
        print(f"Done. {n} files in vault_encrypted/")

    elif args.cmd == "decrypt":
        content = decrypt_skill(Path(args.file), args.key, args.machine)
        print(content)

    elif args.cmd == "verify":
        mid = args.machine or get_machine_id()
        ok  = verify_key(args.key, mid)
        print(f"Key valid: {ok}")
        sys.exit(0 if ok else 1)

    elif args.cmd == "machine-id":
        print(get_machine_id())

    else:
        p.print_help()
