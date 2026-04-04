"""CLI for obsidian-wiki-mcp — vault initialization and management."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

SCAFFOLD_DIR = Path(__file__).parent / "scaffold"


def init_vault(vault_path: str, skip_git: bool = False) -> None:
    """Initialize a new Obsidian wiki vault with all required structure."""
    vault = Path(vault_path).resolve()

    if vault.exists() and any(vault.iterdir()):
        # Vault exists — check if it's already initialized
        if (vault / "_schemas").exists():
            print(f"⚠  Vault at {vault} already has _schemas/. Updating scaffold files...")
            _copy_scaffold(vault, overwrite=False)
            print("✓  Updated missing files (existing files were not overwritten).")
            return
        else:
            print(f"Found existing directory at {vault}. Adding wiki structure...")
            _copy_scaffold(vault, overwrite=False)
    else:
        vault.mkdir(parents=True, exist_ok=True)
        _copy_scaffold(vault, overwrite=True)

    # Create content directories
    dirs = [
        "knowledge/concepts",
        "knowledge/tools",
        "knowledge/people",
        "knowledge/resources/attachments",
        "work/daily",
        "work/projects",
    ]
    for d in dirs:
        (vault / d).mkdir(parents=True, exist_ok=True)

    # Create empty references.bib
    bib = vault / "references.bib"
    if not bib.exists():
        bib.write_text("% BibTeX references for the wiki\n% Add entries here and reference them via bibtex_key in resource pages.\n\n")

    # Create .gitignore
    gitignore = vault / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(
            "# Obsidian internals\n"
            ".obsidian/workspace.json\n"
            ".obsidian/workspace-mobile.json\n"
            ".trash/\n"
            "\n"
            "# Raw files\n"
            "*.pdf\n"
            "knowledge/resources/attachments/\n"
            "work/projects/*/attachments/\n"
            "\n"
            "# OS\n"
            ".DS_Store\n"
            "Thumbs.db\n"
        )

    # Initialize git
    if not skip_git and not (vault / ".git").exists():
        try:
            subprocess.run(["git", "init"], cwd=vault, check=True, capture_output=True)
            subprocess.run(["git", "add", "-A"], cwd=vault, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Initialize wiki vault"],
                cwd=vault, check=True, capture_output=True,
            )
            print("✓  Git repository initialized with initial commit.")
        except FileNotFoundError:
            print("⚠  Git not found — skipping git init. Install git and run `git init` manually.")
        except subprocess.CalledProcessError as e:
            print(f"⚠  Git init issue: {e}. You may need to configure git user.name and user.email.")

    # Print summary
    print()
    print(f"✓  Wiki vault initialized at: {vault}")
    print()
    print("   Structure:")
    print("   ├── CLAUDE.md                    ← Agent identity (read every session)")
    print("   ├── .claude/commands/")
    print("   │   ├── wiki.md                  ← /wiki command")
    print("   │   ├── wiki-audit.md            ← /wiki-audit command")
    print("   │   └── wiki-ingest.md           ← /wiki-ingest command")
    print("   ├── _schemas/                    ← Page type definitions")
    print("   ├── _wiki/style-guide.md         ← Writing conventions")
    print("   ├── references.bib               ← BibTeX citations")
    print("   ├── knowledge/")
    print("   │   ├── concepts/")
    print("   │   ├── tools/")
    print("   │   ├── people/")
    print("   │   └── resources/attachments/")
    print("   └── work/projects/")
    print()
    print("   Next steps:")
    print(f"   1. Open {vault} in Obsidian")
    print(f"   2. Configure the MCP server:")
    print()
    print(f'      Add to .mcp.json (in the vault root):')
    print()
    print(f'      {{')
    print(f'        "mcpServers": {{')
    print(f'          "obsidian-wiki": {{')
    print(f'            "command": "obsidian-wiki-mcp",')
    print(f'            "env": {{ "VAULT_PATH": "{vault}" }}')
    print(f'          }}')
    print(f'        }}')
    print(f'      }}')
    print()
    print(f"   3. Run `claude` in the vault directory")
    print(f"   4. Try: /wiki create a concept page about something you're working on")


def _copy_scaffold(vault: Path, overwrite: bool = True) -> None:
    """Copy scaffold files into the vault."""
    if not SCAFFOLD_DIR.exists():
        print(f"Error: scaffold directory not found at {SCAFFOLD_DIR}", file=sys.stderr)
        sys.exit(1)

    for src in SCAFFOLD_DIR.rglob("*"):
        if src.is_file():
            rel = src.relative_to(SCAFFOLD_DIR)
            dest = vault / rel
            if dest.exists() and not overwrite:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        prog="obsidian-wiki-init",
        description="Initialize an Obsidian vault as a structured wiki.",
    )
    parser.add_argument(
        "vault_path",
        help="Path to the vault directory (will be created if it doesn't exist)",
    )
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="Skip git initialization",
    )

    args = parser.parse_args()
    init_vault(args.vault_path, skip_git=args.no_git)


if __name__ == "__main__":
    main()
