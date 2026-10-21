"""Prepare a reviewable source snapshot; never publish, commit, or include secrets."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".artifacts/integration_candidate"
SOURCE_DIRS = {"analytics", "pages", "src", "utils", "tests", "qa", "docs", "assets", "config"}
ROOT_FILES = {"README.md", "requirements.txt", "requirements-dev.txt", ".gitignore", "pytest.ini", "pyproject.toml"}


def main():
    readiness = "--readiness" in sys.argv
    three = "--three" in sys.argv or readiness
    OUTPUT.mkdir(parents=True, exist_ok=True)
    git_files = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT).decode().split("\0")
    selected = []
    for name in sorted(set(git_files)):
        if not name:
            continue
        path = Path(name)
        approved = ((len(path.parts) == 1 and (path.suffix == ".py" or name in ROOT_FILES))
                    or (path.parts[0] in SOURCE_DIRS and path.suffix.lower() in {".py", ".md", ".csv", ".json", ".png", ".svg", ".toml"})
                    or name in {".streamlit/config.toml", ".streamlit/secrets.toml.example"})
        approved = approved or (name.startswith("validation_outputs/integration_qa/")
                                and path.suffix in {".json", ".png", ".txt"}
                                and path.name != "package_receipt.json")
        approved = approved or (name.startswith(("validation_outputs/forecast_accuracy/", "validation_outputs/approved_mca/", "validation_outputs/five_criterion_mca/"))
                                and path.suffix in {".json", ".csv"})
        approved = approved or (three and name.startswith("validation_outputs/three_criterion_mca/")
                                and path.suffix in {".json", ".csv", ".txt", ".png"}
                                and path.name != "package_receipt.json")
        approved = approved or (readiness and name.startswith("validation_outputs/integration_readiness/")
                                and path.suffix in {".json", ".csv", ".txt"}
                                and path.name != "package_receipt.json")
        if approved and (ROOT / path).is_file() and "__pycache__" not in path.parts:
            selected.append(name)
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in selected}
    data = {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "final_outputs").glob("*.csv"))}
    snapshot_id = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    manifest = {"snapshot_id": snapshot_id, "git_base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
                "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT).decode().strip(),
                "source_files": hashes, "required_governed_data": data,
                "scope": "Uncommitted source snapshot. Governed datasets, raw data, real secrets, runtime databases and local logs are not bundled. Supply the existing authorized data handoff separately."}
    if readiness:
        evidence = json.loads((ROOT / "validation_outputs/integration_readiness/summary.json").read_text())
        manifest["corrected_candidate_data"] = evidence["candidate_files"]
        manifest["data_instruction"] = (
            "required_governed_data records the original audit inputs. For the corrected candidate, "
            "use the coherent corrected CSV/database set described in "
            "docs/corrected_candidate_integration_handoff.md and corrected_candidate_data hashes. "
            "Private data is supplied separately; final weights remain provisional.")
    archive = OUTPUT / ("tesph_sku_corrected_readiness_candidate.zip" if readiness else
                        "tesph_three_criterion_provisional.zip" if three else "tesph_integration_candidate.zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name in selected:
            bundle.write(ROOT / name, name)
        bundle.writestr("CANDIDATE_MANIFEST.json", json.dumps(manifest, indent=2))
        freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], cwd=ROOT).decode()
        bundle.writestr("tested-environment.txt", freeze)
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        for name, digest in hashes.items():
            assert hashlib.sha256(bundle.read(name)).hexdigest() == digest
        assert not any(name.endswith("secrets.toml") or name.endswith(".db") for name in bundle.namelist())
    (OUTPUT / ("readiness_manifest.json" if readiness else "three_criterion_manifest.json" if three else "manifest.json")).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    receipt = {"snapshot_id": snapshot_id, "source_file_count": len(selected), "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
               "archive_bytes": archive.stat().st_size, "archive": str(archive), "checks": "ZIP integrity and every source checksum verified"}
    receipt_dir = ("validation_outputs/integration_readiness" if readiness else
                   "validation_outputs/three_criterion_mca" if three else "validation_outputs/integration_qa")
    (ROOT / receipt_dir / "package_receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
