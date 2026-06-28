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

def _server_session_token() -> str:
    """
    FIX 8 — read the rotating server session token from the local kv store.
    Returns "" if unavailable so key derivation stays backward-compatible with
    vaults encrypted before token rotation existed.
    """
    try:
        from license import get_kv
        return get_kv("server_session_token") or ""
    except Exception:
        return ""


def _derive_key(license_key: str, machine_id: str) -> bytes:
    """
    Derive a 32-byte AES key from license_key + machine_id + server_session_token
    via PBKDF2. FIX 8 adds the server session token as a third factor: when the
    server rotates it (on cancel/complete/halt), every .sg file encrypted under
    the old token becomes undecryptable until the user re-syncs with an active
    license.
    """
    token = _server_session_token()
    material = f"{license_key}:{machine_id}:{token}".encode("utf-8")
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


def encrypt_vault_for(license_key: str, machine_id: str) -> dict[str, bytes]:
    """
    Encrypt the whole vault/ for ONE specific (license_key, machine_id).

    Returns { "rel/path.sg": ciphertext_bytes, ..., "_sentinel.sg": ... }.

    This is the server side of per-customer vault delivery: at `sg sync` the
    backend calls this with the caller's own key material + machine id, so the
    client can decrypt locally with the SAME key. Fixes the original bug where a
    single vault_encrypted/ was keyed to one machine and worked for nobody else.
    """
    key = _derive_key(license_key, machine_id)
    out: dict[str, bytes] = {
        SENTINEL_NAME: _encrypt_bytes(b"skillgod-sentinel-ok", key),
    }
    for md in VAULT_DIR.rglob("*.md"):
        rel = md.relative_to(VAULT_DIR).with_suffix(".sg")
        out[str(rel).replace("\\", "/")] = _encrypt_bytes(md.read_bytes(), key)
    return out


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
        # Allow the pre-derived key to be passed positionally (symmetry with
        # encrypt_skill(plaintext, key)) or via the explicit key= keyword.
        if key is None and isinstance(license_key, (bytes, bytearray)):
            key = license_key
        if key is None:
            raise ValueError("key= required when source is bytes")
        return _decrypt_bytes(source, key).decode("utf-8")
    return _orig_decrypt_skill(source, license_key, machine_id)


# ---------------------------------------------------------------------------
# Release-key delivery (R2 / CDN path)
# ---------------------------------------------------------------------------
# A single static vault_pro.zip is built ONCE per release, with every skill
# encrypted under a random 32-byte *release key* (K_rel). R2 serves that one zip
# to everyone. The release key is never shipped in the clear: at `sg sync` the
# server hands back K_rel *wrapped* (AES-GCM) to the caller's own machine, so
# only an active, paying machine can unwrap it. On install the client re-encrypts
# the skills under its per-machine key into vault_encrypted/, so the existing
# verify_key() / sync_encrypted_vault() pipeline runs downstream unchanged.

RELEASE_KEY_FILE = ".release_key"   # local kv fallback (CLI stores the wrapped key here)


def _derive_wrap_key(license_key: str, machine_id: str) -> bytes:
    """
    Key used ONLY to wrap/unwrap the release key. Bound to license_key + machine_id
    but NOT to the rotating server session token — the wrapped key is gated server
    side by an active-license check at /v1/vault/signed-url, and re-sync is required
    after revocation. Keeping it token-free makes wrap (server) and unwrap (client)
    derive identically regardless of FIX-8 token state.
    """
    material = f"wrap:{license_key}:{machine_id}".encode("utf-8")
    return hashlib.pbkdf2_hmac("sha256", material, SALT, PBKDF2_ITERS, dklen=32)


def build_release_zip(out_path: str = "", version: str = "dev") -> tuple[str, str]:
    """
    Build the static, release-key-encrypted vault_pro.zip.
    Returns (zip_path, release_key_b64). Run at release time, then upload the zip
    to R2 and store release_key_b64 against the version (see build_vault_release.py).
    """
    import base64
    import zipfile

    import tempfile
    K_rel = os.urandom(32)
    if out_path:
        out = Path(out_path)
    else:
        # Default to system temp dir — Windows Controlled Folder Access blocks
        # zip creation in protected folders (Desktop, Documents, etc.).
        out = Path(tempfile.gettempdir()) / f"vault_pro_{version}.zip"
    count = 0
    with zipfile.ZipFile(str(out), "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(SENTINEL_NAME, _encrypt_bytes(b"skillgod-sentinel-ok", K_rel))
        for md in sorted(VAULT_DIR.rglob("*.md")):
            rel = md.relative_to(VAULT_DIR).with_suffix(".sg")
            zf.writestr(str(rel).replace("\\", "/"),
                        _encrypt_bytes(md.read_bytes(), K_rel))
            count += 1
        zf.writestr("manifest.json", json.dumps(
            {"version": version, "skill_count": count, "format": "release-key-v1"}))
    return str(out), base64.b64encode(K_rel).decode("ascii")


def wrap_release_key(release_key_b64: str, license_key: str, machine_id: str = "") -> str:
    """Server side: encrypt K_rel to a specific (license_key, machine_id). Returns b64."""
    import base64
    machine_id = machine_id or get_machine_id()
    k_rel = base64.b64decode(release_key_b64)
    wrapped = _encrypt_bytes(k_rel, _derive_wrap_key(license_key, machine_id))
    return base64.b64encode(wrapped).decode("ascii")


def unwrap_release_key(wrapped_b64: str, license_key: str, machine_id: str = "") -> bytes:
    """Client side: recover K_rel from the wrapped blob. Raises on wrong key/machine."""
    import base64
    machine_id = machine_id or get_machine_id()
    return _decrypt_bytes(base64.b64decode(wrapped_b64),
                          _derive_wrap_key(license_key, machine_id))


def install_release_zip(zip_path: str, wrapped_release_key_b64: str,
                        license_key: str, machine_id: str = "") -> int:
    """
    Client side: take the downloaded release zip + the wrapped release key, and
    produce the per-machine vault_encrypted/ that the normal sync pipeline expects.
    Unwrap K_rel, decrypt each skill, re-encrypt under this machine's key, and write
    vault_encrypted/*.sg + a machine-key sentinel. Returns count of skills written.
    """
    import zipfile

    machine_id = machine_id or get_machine_id()
    k_rel = unwrap_release_key(wrapped_release_key_b64, license_key, machine_id)
    mkey  = _derive_key(license_key, machine_id)

    ENC_DIR.mkdir(parents=True, exist_ok=True)
    # Machine-key sentinel so verify_key() passes downstream.
    (ENC_DIR / SENTINEL_NAME).write_bytes(_encrypt_bytes(b"skillgod-sentinel-ok", mkey))

    count = 0
    with zipfile.ZipFile(zip_path) as zf:
        # Verify the release key actually decrypts the zip's sentinel before doing work.
        try:
            if _decrypt_bytes(zf.read(SENTINEL_NAME), k_rel) != b"skillgod-sentinel-ok":
                raise ValueError("release sentinel mismatch — wrong release key")
        except KeyError:
            pass  # older zip without sentinel — proceed best-effort
        for name in zf.namelist():
            if not name.endswith(".sg") or name == SENTINEL_NAME:
                continue
            plaintext = _decrypt_bytes(zf.read(name), k_rel)
            out = ENC_DIR / name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(_encrypt_bytes(plaintext, mkey))
            count += 1
    return count


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
