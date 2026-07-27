from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from shared.paths import github_pages_config_path, repo_root


DEFAULT_BRANCH = "gh-pages"
DEFAULT_BASE_URL = "https://thombay.github.io/PoGo_XP"


@dataclass(frozen=True)
class GithubPagesConfig:
    enabled: bool = True
    branch: str = DEFAULT_BRANCH
    base_url: str = DEFAULT_BASE_URL
    commit_message: str = "Update hosted dashboard exports"


def default_github_pages_config() -> dict[str, Any]:
    return {
        "enabled": True,
        "branch": DEFAULT_BRANCH,
        "base_url": DEFAULT_BASE_URL,
        "commit_message": "Update hosted dashboard exports",
    }


def load_github_pages_config(path: Path | None = None) -> GithubPagesConfig:
    config_path = path or github_pages_config_path()
    raw: dict[str, Any] = default_github_pages_config()
    if config_path.exists():
        loaded = json.loads(config_path.read_text(encoding="utf-8-sig"))
        if isinstance(loaded, dict):
            raw.update({k: loaded.get(k, raw[k]) for k in raw.keys()})
    return GithubPagesConfig(
        enabled=bool(raw.get("enabled", True)),
        branch=str(raw.get("branch") or DEFAULT_BRANCH).strip() or DEFAULT_BRANCH,
        base_url=str(raw.get("base_url") or DEFAULT_BASE_URL).rstrip("/"),
        commit_message=str(raw.get("commit_message") or "Update hosted dashboard exports"),
    )


def save_github_pages_config(config: dict[str, Any] | GithubPagesConfig, path: Path | None = None) -> Path:
    config_path = path or github_pages_config_path()
    if isinstance(config, GithubPagesConfig):
        payload = {
            "enabled": config.enabled,
            "branch": config.branch,
            "base_url": config.base_url,
            "commit_message": config.commit_message,
        }
    else:
        payload = {**default_github_pages_config(), **config}
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return config_path


def slugify_path_segment(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^\w\-]+", "", text, flags=re.UNICODE)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "untitled"


def export_relative_dir(dashboard: str, group: str) -> Path:
    return Path(slugify_path_segment(dashboard)) / slugify_path_segment(group)


def export_pages_url(base_url: str, dashboard: str, group: str) -> str:
    rel = export_relative_dir(dashboard, group).as_posix()
    return f"{base_url.rstrip('/')}/{rel}/"


def write_export_site(
    site_dir: Path,
    pages: list[dict[str, str]],
) -> list[dict[str, str]]:
    """
    Write dashboard HTML pages into site_dir.

    pages items: {"dashboard", "group", "html"}
    Returns rows with relative_path and url_path fields filled by caller via base_url later.
    """
    if site_dir.exists():
        shutil.rmtree(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")

    written: list[dict[str, str]] = []
    for page in pages:
        dashboard = str(page.get("dashboard", "")).strip()
        group = str(page.get("group", "")).strip()
        html = str(page.get("html", ""))
        rel_dir = export_relative_dir(dashboard, group)
        target_dir = site_dir / rel_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / "index.html"
        target_file.write_text(html, encoding="utf-8")
        written.append(
            {
                "dashboard": dashboard,
                "group": group,
                "relative_path": rel_dir.as_posix() + "/index.html",
                "url_path": rel_dir.as_posix() + "/",
            }
        )
    return written


def _run_git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=False,
        text=True,
        capture_output=True,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result



def remote_branch_exists(repo: Path, branch: str, remote: str = "origin") -> bool:
    result = _run_git(["ls-remote", "--heads", remote, branch], cwd=repo, check=False)
    if result.returncode != 0:
        return False
    return any(line.strip().endswith(f"refs/heads/{branch}") for line in result.stdout.splitlines())


def publish_site_dir_to_gh_pages(
    site_dir: Path,
    *,
    repo: Path | None = None,
    branch: str = DEFAULT_BRANCH,
    remote: str = "origin",
    commit_message: str = "Update hosted dashboard exports",
) -> dict[str, Any]:
    """Replace gh-pages branch contents with site_dir and push to remote."""
    root = repo or repo_root()
    site_dir = site_dir.resolve()
    if not site_dir.exists() or not any(site_dir.iterdir()):
        raise FileNotFoundError(f"GitHub Pages site directory is empty or missing: {site_dir}")

    worktree = root / ".gh-pages-worktree"
    if worktree.exists():
        _run_git(["worktree", "remove", "--force", str(worktree)], cwd=root, check=False)
        if worktree.exists():
            shutil.rmtree(worktree, ignore_errors=True)

    try:
        if remote_branch_exists(root, branch, remote=remote):
            _run_git(["fetch", remote, branch], cwd=root)
            # -B checks out/resets a real local branch (not detached HEAD), so commit+push update gh-pages.
            _run_git(["worktree", "add", "--force", "-B", branch, str(worktree), f"{remote}/{branch}"], cwd=root)
        else:
            _run_git(["worktree", "add", "--force", "--orphan", "-b", branch, str(worktree)], cwd=root)

        # Clear existing published files (keep .git via worktree metadata outside dir contents).
        for child in worktree.iterdir():
            if child.name == ".git":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

        for item in site_dir.iterdir():
            target = worktree / item.name
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)

        _run_git(["add", "-A"], cwd=worktree)
        status = _run_git(["status", "--porcelain"], cwd=worktree)
        if not status.stdout.strip():
            return {
                "ok": True,
                "pushed": False,
                "branch": branch,
                "message": "No GitHub Pages changes to publish.",
            }

        _run_git(["commit", "-m", commit_message], cwd=worktree)
        head = _run_git(["rev-parse", "HEAD"], cwd=worktree).stdout.strip()
        push = _run_git(["push", "-u", remote, f"HEAD:refs/heads/{branch}"], cwd=worktree)
        return {
            "ok": True,
            "pushed": True,
            "branch": branch,
            "commit": head,
            "message": push.stdout.strip() or f"Pushed {branch} ({head[:7]})",
        }
    finally:
        _run_git(["worktree", "remove", "--force", str(worktree)], cwd=root, check=False)
        if worktree.exists():
            shutil.rmtree(worktree, ignore_errors=True)


def publish_html_to_github_pages(
    *,
    targets: list[dict[str, Any]],
    build_html: Callable[[str, str, str, int], str],
    export_mode: str,
    window_days: int,
    site_dir: Path,
    pages_config: GithubPagesConfig | None = None,
    push: bool = True,
    repo: Path | None = None,
) -> dict[str, Any]:
    cfg = pages_config or load_github_pages_config()
    if not cfg.enabled:
        return {
            "ok": False,
            "skipped": True,
            "uploaded": 0,
            "total": 0,
            "results": [],
            "error": "GitHub Pages publishing is disabled in config.",
        }

    pages: list[dict[str, str]] = []
    results: list[dict[str, Any]] = []
    for row in targets:
        dashboard = str(row.get("dashboard", "")).strip()
        group = str(row.get("group", "")).strip()
        if not dashboard or not group:
            continue
        try:
            html = build_html(dashboard, group, export_mode, window_days)
            pages.append({"dashboard": dashboard, "group": group, "html": html})
            url = export_pages_url(cfg.base_url, dashboard, group)
            results.append(
                {
                    "dashboard": dashboard,
                    "group": group,
                    "ok": True,
                    "web_view_link": url,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "dashboard": dashboard,
                    "group": group,
                    "ok": False,
                    "error": str(exc),
                }
            )

    if not pages:
        return {
            "ok": False,
            "skipped": True,
            "uploaded": 0,
            "total": 0,
            "results": results,
            "error": "No GitHub Pages export targets to publish.",
        }

    write_export_site(site_dir, pages)
    push_result: dict[str, Any] = {"ok": True, "pushed": False, "message": "Push skipped."}
    if push:
        push_result = publish_site_dir_to_gh_pages(
            site_dir,
            repo=repo,
            branch=cfg.branch,
            commit_message=cfg.commit_message,
        )

    ok_count = sum(1 for item in results if item.get("ok"))
    return {
        "ok": ok_count > 0 and all(item.get("ok") for item in results) and bool(push_result.get("ok")),
        "uploaded": ok_count,
        "total": len(results),
        "results": results,
        "push": push_result,
        "site_dir": str(site_dir),
        "base_url": cfg.base_url,
    }


def format_github_pages_summary(publish_result: dict[str, Any]) -> str:
    lines: list[str] = []
    uploaded = int(publish_result.get("uploaded") or 0)
    total = int(publish_result.get("total") or 0)
    lines.append(f"GitHub Pages exports updated: {uploaded}/{total}")
    for item in list(publish_result.get("results") or []):
        dashboard = item.get("dashboard", "?")
        group = item.get("group", "?")
        if item.get("ok"):
            link = item.get("web_view_link") or "(no link)"
            lines.append(f"- {dashboard} / {group}: {link}")
        else:
            lines.append(f"- {dashboard} / {group}: failed ({item.get('error', 'unknown error')})")
    push = publish_result.get("push") or {}
    if push.get("message"):
        lines.append(str(push.get("message")))
    return "\n".join(lines)
