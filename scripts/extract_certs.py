"""Extract the full CA chain needed behind a TLS-inspecting proxy into CA_BUNDLE_DIR.

On a network that re-signs TLS (for example AVD), containers must trust the whole
chain up to a self-signed root. The proxy only presents part of it during the
handshake -- the certificates above are installed on the machine, not sent -- so a
bundle built from the handshake alone fails with "unable to get issuer certificate".

This script combines both sources: it takes the chain a probe host actually serves,
then walks upwards through the machine's own trust stores (the Windows certificate
store under WSL, plus the Linux stores) until it reaches a self-signed root. Each
certificate authority in that chain is written to CA_BUNDLE_DIR as a PEM file.

    uv run task certs

CA_BUNDLE_DIR is read from .env (see the README). Re-run whenever the corporate
certificates are rotated -- `docker compose up --build` picks up the change.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import certifi
from dotenv import find_dotenv, load_dotenv

# Resolved once so the subprocess calls below use an absolute path.
OPENSSL = shutil.which("openssl") or "/usr/bin/openssl"

CERT_BEGIN = "-----BEGIN CERTIFICATE-----"
CERT_END = "-----END CERTIFICATE-----"

# Any host the proxy intercepts will do; these are the ones the services call.
PROBE_HOSTS = (
    "bedrock-runtime.eu-west-2.amazonaws.com",
    "pypi.org",
)

LINUX_STORES = (
    Path("/etc/ssl/certs/ca-certificates.crt"),
    Path("/usr/local/share/ca-certificates"),
)

POWERSHELL_STORES = r"Cert:\LocalMachine\Root, Cert:\LocalMachine\CA"


def split_pems(text: str) -> list[str]:
    """Return each PEM certificate block in ``text``, ignoring anything around them."""
    blocks = []
    for chunk in text.split(CERT_END):
        if CERT_BEGIN in chunk:
            blocks.append(chunk[chunk.index(CERT_BEGIN) :].strip() + "\n" + CERT_END)
    return blocks


def describe(pems: list[str]) -> list[tuple[str, str]]:
    """Return (subject, issuer) for each PEM, in order.

    Uses two openssl calls for the whole list rather than one per certificate: a
    machine trust store holds hundreds of them and per-cert subprocesses are slow.
    """
    if not pems:
        return []
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as handle:
        handle.write("\n".join(pems))
        path = handle.name
    try:
        pkcs7 = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [OPENSSL, "crl2pkcs7", "-nocrl", "-certfile", path],
            capture_output=True,
            check=True,
        )
        text = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [OPENSSL, "pkcs7", "-print_certs", "-noout"],
            input=pkcs7.stdout,
            capture_output=True,
            check=True,
        ).stdout.decode()
    finally:
        os.unlink(path)
    subjects = re.findall(r"^subject=(.*)$", text, re.MULTILINE)
    issuers = re.findall(r"^issuer=(.*)$", text, re.MULTILINE)
    return list(zip(subjects, issuers, strict=True))


def served_chain(host: str) -> list[str]:
    """Return the certificate chain ``host`` presents, as PEM blocks."""
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            OPENSSL,
            "s_client",
            "-showcerts",
            "-servername",
            host,
            "-connect",
            f"{host}:443",
        ],
        input=b"",
        capture_output=True,
        timeout=30,
    )
    return split_pems(result.stdout.decode(errors="replace"))


def machine_certs() -> list[str]:
    """Every CA certificate installed on this machine, from Windows and Linux stores."""
    pems: list[str] = []
    powershell = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    if Path(powershell).exists():
        command = (
            f"Get-ChildItem -Path {POWERSHELL_STORES} | ForEach-Object {{ "
            "'-----BEGIN CERTIFICATE-----'; "
            "[Convert]::ToBase64String($_.RawData, 'InsertLineBreaks'); "
            "'-----END CERTIFICATE-----' }"
        )
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [powershell, "-NoProfile", "-Command", command],
            capture_output=True,
            timeout=180,
        )
        pems += split_pems(result.stdout.decode(errors="replace").replace("\r", ""))
    for store in LINUX_STORES:
        files = sorted(store.glob("*.crt")) if store.is_dir() else [store]
        for path in files:
            if path.is_file():
                pems += split_pems(path.read_text(errors="replace"))
    return pems


def build_chain(leaf_chain: list[str], pool: list[str]) -> tuple[list[str], str | None]:
    """Walk up from the served chain through ``pool`` until a self-signed root.

    Returns the certificate authorities needed (the leaf is dropped -- it is the
    server's own certificate, not something to trust) and the subject of a missing
    issuer if the chain could not be completed.
    """
    by_subject = {
        subject: pem for pem, (subject, _) in zip(pool, describe(pool), strict=True)
    }
    chain = list(leaf_chain)
    while True:
        subject, issuer = describe([chain[-1]])[0]
        if subject == issuer:  # self-signed: we have reached the root
            break
        parent = by_subject.get(issuer)
        if parent is None:
            return chain[1:], issuer
        chain.append(parent)
    return chain[1:], None


def target_directory() -> Path | None:
    """The configured CA_BUNDLE_DIR, taking .env into account, or None with a warning."""
    load_dotenv(find_dotenv(usecwd=True))
    target = os.environ.get("CA_BUNDLE_DIR")
    if not target:
        print(
            "CA_BUNDLE_DIR is not set.\n"
            "Add it to .env, pointing at the directory to write certificates to:\n"
            "    CA_BUNDLE_DIR=/path/to/certs\n"
            "See 'Corporate proxy / custom CAs' in the README.",
            file=sys.stderr,
        )
        return None
    directory = Path(target).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def collect(
    pool: list[str], public_roots: set[str]
) -> tuple[dict[str, str], list[str]]:
    """Probe each host and return the CAs to trust, keyed by subject, plus any problems."""
    written: dict[str, str] = {}
    incomplete: list[str] = []
    for host in PROBE_HOSTS:
        chain = served_chain(host)
        if not chain:
            print(f"  {host}: no certificates returned, skipping")
            continue
        authorities, missing = build_chain(chain, pool)
        subjects = [subject for subject, _ in describe(authorities)]
        if not missing and subjects and subjects[-1] in public_roots:
            print(f"  {host}: publicly trusted, nothing to add")
            continue
        print(f"  {host}: {' -> '.join(subjects) or '(no intermediate CAs)'}")
        if missing:
            incomplete.append(f"{host}: could not find issuer {missing!r}")
        for pem, subject in zip(authorities, subjects, strict=True):
            written[subject] = pem
    return written, incomplete


def main() -> int:
    directory = target_directory()
    if directory is None:
        return 2

    print("Reading machine trust stores...")
    pool = machine_certs()
    print(f"  {len(pool)} certificates available locally")

    # The containers already ship the public roots, so a chain ending in one of
    # them needs nothing added -- only privately-rooted (proxy) chains matter.
    public_pems = split_pems(Path(certifi.where()).read_text())
    public_roots = {subject for subject, _ in describe(public_pems)}

    written, incomplete = collect(pool, public_roots)

    if not written:
        print("\nNothing to write: this connection does not appear to be intercepted.")
        return 0

    for subject, pem in written.items():
        name = (
            re.sub(r"[^A-Za-z0-9]+", "-", subject.split("CN=")[-1]).strip("-").lower()
        )
        (directory / f"{name}.crt").write_text(pem + "\n")

    print(f"\nWrote {len(written)} certificate(s) to {directory}:")
    for path in sorted(directory.glob("*.crt")):
        print(f"  {path.name}")

    if incomplete:
        print(
            "\nWARNING: chain incomplete -- verification will still fail:",
            file=sys.stderr,
        )
        for problem in incomplete:
            print(f"  {problem}", file=sys.stderr)
        print(
            "Install the missing root in your machine trust store and re-run.",
            file=sys.stderr,
        )
        return 1

    print(
        "\nRun `docker compose up --build` to rebuild the services with these certificates."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
