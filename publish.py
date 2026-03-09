#!/usr/bin/env python3
"""
publish.py
----------
Strips, cleans, and publishes a Jupyter notebook to a separate public repo.

Usage:
    python publish.py                        # uses config defaults
    python publish.py my_notebook.ipynb      # override notebook path
    python publish.py --commit               # auto-commit after copying
    python publish.py --push                 # auto-commit AND push
    python publish.py --no-commit --no-push  # explicitly disable both

    .venv/bin/python3 python/publish.py
    .venv/bin/python3 python/publish.py python/tmp.ipynb
    .venv/bin/python3 python/publish.py --push

Setup:
    pip install nbconvert nbstripout nb-clean pipreqs

Config:
    Edit the CONFIG block below. CLI flags override config values.
"""

import argparse
import subprocess
import shutil
import sys
import os
import json
from pathlib import Path

from nbconvert import NotebookExporter
from nbconvert.preprocessors import TagRemovePreprocessor
import nbformat
from traitlets.config import Config

CONFIG = {
    # Path to the notebook to publish (relative to this script)
    "notebook": "python/cm1-p2-cw-notebook.ipynb",
    # Local path to cloned public repo
    "public_repo_path": "../a_smm065_cm1(2)_excel_coursework_public",
    # Subfolder inside the public repo to put the notebook (or "" for root)
    "public_subfolder": "",
    # "blocklist" — tag cells to REMOVE (e.g. tag: "remove_cell")
    # "allowlist" — tag cells to KEEP  (e.g. tag: "publish"); all others are removed
    "filter_mode": "allowlist",
    #
    # Cell tags that should be stripped before publishing
    "remove_tags": ["remove_cell", "private"],
    "keep_tags": ["publish"],  # used in allowlist mode
    #
    # strip outputs (True = clean slate)
    "strip_outputs": False,
    # regenerate requirements.txt
    "generate_requirements": False,  # takes too long
    # auto-commit after copying
    "auto_commit": False,
    # auto-commit and push the public repo after copying
    # ! DON'T SET TO TRUE AND AUTO_COMMIT=FALSE
    "auto_push": False,
    # commit message (use {notebook} as a placeholder)
    "commit_message": "Update {notebook}",
}

# ─────────────────────────────────────────
# CLI
# ─────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Strip, clean, and publish a Jupyter notebook to a public repo."
    )
    parser.add_argument(
        "notebook",
        nargs="?",
        default=None,
        help=f"Path to the notebook (default: {CONFIG['notebook']})",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        default=None,
        help="Auto-commit the public repo after copying",
    )
    parser.add_argument(
        "--no-commit",
        action="store_true",
        default=False,
        help="Do not auto-commit (overrides config)",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        default=None,
        help="Auto-commit and push the public repo (implies --commit)",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        default=False,
        help="Do not auto-push (overrides config)",
    )
    parser.add_argument(
        "-m",
        "--message",
        default=None,
        help="Commit message (use {notebook} as placeholder)",
    )
    return parser.parse_args()


def apply_cli_overrides(args: argparse.Namespace):
    """Merge CLI flags into CONFIG, with CLI taking precedence."""
    if args.notebook is not None:
        CONFIG["notebook"] = args.notebook

    # --push implies --commit
    if args.push:
        CONFIG["auto_commit"] = True
        CONFIG["auto_push"] = True
    if args.commit:
        CONFIG["auto_commit"] = True

    # --no-* flags override everything
    if args.no_push:
        CONFIG["auto_push"] = False
    if args.no_commit:
        CONFIG["auto_commit"] = False
        CONFIG["auto_push"] = False  # can't push without committing

    if args.message is not None:
        CONFIG["commit_message"] = args.message


# HELPERS


def run(cmd: list[str], cwd=None, check=True) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def require_tool(name: str):
    if not shutil.which(name):
        print(f"  ✗ '{name}' not found. Run: pip install {name}")
        sys.exit(1)


def check_dependencies():
    print("\n[1/5] Checking dependencies...")
    for tool in ["jupyter", "nbstripout", "pipreqs"]:
        require_tool(tool)
    print("  ✓ All tools found.")


def filter_cells(nb):
    mode = CONFIG["filter_mode"]
    original_count = len(nb.cells)

    if mode == "blocklist":
        remove_tags = set(CONFIG["remove_tags"])
        nb.cells = [
            cell
            for cell in nb.cells
            if not remove_tags.intersection(cell.get("metadata", {}).get("tags", []))
        ]
    elif mode == "allowlist":
        keep_tags = set(CONFIG["keep_tags"])
        remove_tags = set(CONFIG["remove_tags"])
        filtered = []
        for cell in nb.cells:
            cell_tags = set(cell.get("metadata", {}).get("tags", []))
            if cell_tags.intersection(keep_tags):
                filtered.append(cell)
            elif cell.cell_type == "markdown" and not cell_tags.intersection(
                remove_tags
            ):
                filtered.append(cell)  # keep markdown default
        nb.cells = filtered

    return nb, original_count - len(nb.cells)


def strip_and_clean(notebook: Path) -> Path:
    """Strip private metadata and tagged cells, return path to cleaned copy."""
    print("\n[2/5] Stripping notebook...")

    # Work on a tmp copy so the original is untouched
    tmp = notebook.with_name(f"_tmp_{notebook.name}")
    shutil.copy(notebook, tmp)

    # filter cells before nb-clean strips tags
    nb = nbformat.read(str(tmp), as_version=4)
    nb, removed = filter_cells(nb)
    mode = CONFIG["filter_mode"]
    tag_used = CONFIG["keep_tags"] if mode == "allowlist" else CONFIG["remove_tags"]
    print(f"  ✓ Cell filter ({mode} {tag_used}): {removed} cell(s) removed.")
    nbformat.write(nb, str(tmp))

    out = notebook.with_name(f"_clean_{notebook.name}")

    # nb-clean
    try:
        run(
            [
                ".venv/bin/python3",
                "-m",
                "nb_clean",
                "clean",
                "--remove-empty-cells",
                "--preserve-cell-outputs",
                str(tmp),
            ]
        )
        print("  ✓ nb-clean applied.")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("  ⚠ nb-clean not available, skipping.")

    shutil.copy(tmp, out)
    tmp.unlink()

    # nbstripout
    if CONFIG["strip_outputs"]:
        run(["nbstripout", str(out)])
        print("  ✓ Outputs stripped via nbstripout.")

    return out


def generate_requirements(notebook_dir: Path, public_dir: Path):
    print("\n[3/5] Generating requirements.txt...")
    result = run(
        [
            "pipreqs",
            str(notebook_dir),
            "--savepath",
            str(public_dir / "requirements.txt"),
            "--force",
        ],
        check=False,
    )
    if result.returncode == 0:
        print("  ✓ requirements.txt written.")
    else:
        print(f"  ⚠ pipreqs failed: {result.stderr.strip()}")


def copy_to_public(cleaned: Path, public_dir: Path):
    print("\n[4/5] Copying to public repo...")
    dest_dir = (
        public_dir / CONFIG["public_subfolder"]
        if CONFIG["public_subfolder"]
        else public_dir
    )
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Use original notebook name (not the _clean_ prefix)
    original_name = cleaned.name.replace("_clean_", "")
    dest = dest_dir / original_name
    shutil.copy(cleaned, dest)
    cleaned.unlink()
    print(f"  ✓ Copied to {dest}")
    return dest


def push_public_repo(public_dir: Path, notebook_name: str):
    print("\n[5/5] Committing and pushing public repo...")
    msg = CONFIG["commit_message"].format(notebook=notebook_name)
    run(["git", "add", "-A"], cwd=public_dir)
    result = run(["git", "diff", "--cached", "--quiet"], cwd=public_dir, check=False)
    if result.returncode == 0:
        print("  ✓ Nothing changed, no commit needed.")
        return
    run(["git", "commit", "-m", msg], cwd=public_dir)
    print("  ✓ Committed.")
    if CONFIG["auto_push"]:
        run(["git", "push"], cwd=public_dir)
        print("  ✓ Pushed.")


def main():
    args = parse_args()
    apply_cli_overrides(args)

    notebook_path = Path(CONFIG["notebook"])
    public_dir = Path(CONFIG["public_repo_path"])

    if not notebook_path.exists():
        print(f"✗ Notebook not found: {notebook_path}")
        sys.exit(1)
    if not public_dir.exists():
        print(f"✗ Public repo path not found: {public_dir}")
        sys.exit(1)

    print(f"\n{'='*50}")
    print(f"  Publishing: {notebook_path.name}")
    print(f"  → {public_dir.resolve()}")
    print(f"  commit={CONFIG['auto_commit']}  push={CONFIG['auto_push']}")
    print(f"{'='*50}")

    check_dependencies()
    cleaned = strip_and_clean(notebook_path)

    if CONFIG["generate_requirements"]:
        generate_requirements(notebook_path.parent, public_dir)

    copy_to_public(cleaned, public_dir)

    if CONFIG["auto_commit"]:
        push_public_repo(public_dir, notebook_path.name)

    print(f"\n✓ Done! {notebook_path.name} acted upon.\n")


if __name__ == "__main__":
    main()
