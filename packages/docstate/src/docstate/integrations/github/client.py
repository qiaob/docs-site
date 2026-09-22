"""A small GitHub REST client for the repository write-back: branches, file
commits, pull requests. Authenticates with a token or, preferably, as a
GitHub App (JWT -> installation token scoped to the one repository; nothing
long-lived leaves the process). Only the calls repo_sync.py needs. The GitHub App
path needs the `github` extra (PyJWT with crypto)."""

from __future__ import annotations

import base64
import datetime as dt
import time
from dataclasses import dataclass
from typing import Any

import httpx


class GitHubError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class RepoFile:
    sha: str
    text: str


@dataclass
class PullRequest:
    number: int
    url: str


class GitHubClient:
    def __init__(
        self,
        repo: str,
        *,
        api_url: str = "https://api.github.com",
        token: str = "",
        app_id: str = "",
        app_private_key: str = "",
        permissions: dict | None = None,
        timeout: float = 30.0,
    ):
        if "/" not in repo:
            raise GitHubError(f"repository must be owner/name, got {repo!r}")
        self.repo = repo
        self._api = api_url.rstrip("/")
        self._token = token
        self._app_id = app_id
        self._app_key = app_private_key
        # narrow the installation token to what this run needs; None = whatever
        # the installation grants (an App with only `actions` cannot ask for more)
        self._permissions = permissions
        self._timeout = timeout
        self._installation_token: tuple[str, float] | None = None

    # ------------------------------------------------------------ auth
    def _auth_token(self) -> str:
        if self._token:
            return self._token
        if not (self._app_id and self._app_key):
            raise GitHubError("no GitHub credential configured (token or app id + private key)")
        if self._installation_token and self._installation_token[1] - 60 > time.time():
            return self._installation_token[0]
        import jwt  # PyJWT[crypto]; imported here so a token-only setup needs no crypto

        now = int(time.time())
        app_jwt = jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": self._app_id},
            self._app_key,
            algorithm="RS256",
        )
        owner, name = self.repo.split("/", 1)
        with httpx.Client(timeout=self._timeout) as http:
            headers = self._headers(app_jwt)
            r = http.get(
                f"{self._api}/app/installations", headers=headers, params={"per_page": 100}
            )
            self._raise(r, "list installations")
            installs = [
                i
                for i in r.json()
                if str(i.get("account", {}).get("login", "")).lower() == owner.lower()
            ]
            if not installs:
                raise GitHubError(f"the GitHub App is not installed on {owner}")
            r = http.post(
                f"{self._api}/app/installations/{installs[0]['id']}/access_tokens",
                headers=headers,
                json={
                    "repositories": [name],
                    **({"permissions": self._permissions} if self._permissions else {}),
                },
            )
            self._raise(r, "mint installation token")
            data = r.json()
        expires = dt.datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")).timestamp()
        self._installation_token = (data["token"], expires)
        return data["token"]

    @staticmethod
    def _headers(token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @staticmethod
    def _raise(r: httpx.Response, what: str) -> None:
        if r.status_code >= 400:
            detail = ""
            try:
                detail = str(r.json().get("message") or "")
            except ValueError:
                detail = r.text[:200]
            raise GitHubError(f"GitHub {what} -> {r.status_code}: {detail}", status=r.status_code)

    def _req(self, method: str, path: str, *, ok404: bool = False, **kw: Any) -> Any:
        with httpx.Client(timeout=self._timeout) as http:
            try:
                r = http.request(
                    method,
                    f"{self._api}/repos/{self.repo}{path}",
                    headers=self._headers(self._auth_token()),
                    **kw,
                )
            except httpx.HTTPError as e:
                raise GitHubError(f"GitHub request failed: {e}") from e
        if ok404 and r.status_code == 404:
            return None
        self._raise(r, f"{method} {path}")
        return r.json() if r.content else {}

    # ------------------------------------------------------------ calls
    def check_access(self) -> dict:
        """The repository as the credential sees it (permissions included)."""
        return self._req("GET", "")

    def branch_sha(self, branch: str) -> str:
        return self._req("GET", f"/git/ref/heads/{branch}")["object"]["sha"]

    def create_branch(self, name: str, sha: str) -> None:
        self._req("POST", "/git/refs", json={"ref": f"refs/heads/{name}", "sha": sha})

    def delete_branch(self, name: str) -> None:
        with httpx.Client(timeout=self._timeout) as http:
            http.delete(
                f"{self._api}/repos/{self.repo}/git/refs/heads/{name}",
                headers=self._headers(self._auth_token()),
            )  # best effort: the branch is disposable

    def get_file(self, path: str, ref: str) -> RepoFile | None:
        data = self._req("GET", f"/contents/{path}", params={"ref": ref}, ok404=True)
        if data is None or data.get("type") != "file":
            return None
        raw = base64.b64decode(data.get("content") or "")
        return RepoFile(sha=data["sha"], text=raw.decode("utf-8", errors="replace"))

    def put_file(
        self,
        path: str,
        text: str,
        *,
        message: str,
        branch: str,
        sha: str | None = None,
        author: dict | None = None,
    ) -> str:
        body: dict = {
            "message": message,
            "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        if author:
            body["author"] = author
        return self._req("PUT", f"/contents/{path}", json=body)["commit"]["sha"]

    def delete_file(
        self, path: str, *, sha: str, message: str, branch: str, author: dict | None = None
    ) -> str:
        body: dict = {"message": message, "sha": sha, "branch": branch}
        if author:
            body["author"] = author
        return self._req("DELETE", f"/contents/{path}", json=body)["commit"]["sha"]

    def dispatch_workflow(self, workflow: str, ref: str, inputs: dict | None = None) -> None:
        """Start a workflow in the repository (the only write an
        actions-scoped credential can make)."""
        self._req(
            "POST",
            f"/actions/workflows/{workflow}/dispatches",
            json={"ref": ref, "inputs": inputs or {}},
        )

    def create_pr(self, *, head: str, base: str, title: str, body: str) -> PullRequest:
        data = self._req(
            "POST", "/pulls", json={"head": head, "base": base, "title": title, "body": body}
        )
        return PullRequest(number=int(data["number"]), url=str(data["html_url"]))

    def merge_pr(self, number: int, *, method: str = "rebase") -> tuple[bool, str]:
        """(merged?, reason). A refusal (review required, not mergeable) is an
        answer, not an error: the PR simply stays open."""
        try:
            data = self._req("PUT", f"/pulls/{number}/merge", json={"merge_method": method})
        except GitHubError as e:
            if e.status in (405, 409, 422):
                return False, str(e)
            raise
        return bool(data.get("merged")), str(data.get("message") or "")

    def pr_state(self, number: int) -> str:
        data = self._req("GET", f"/pulls/{number}")
        if data.get("merged"):
            return "merged"
        return "open" if data.get("state") == "open" else "closed"
