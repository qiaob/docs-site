"""GitHub write-back: every live document on the site is kept in a git
repository, so git stays the source of truth for what the site shows.

Off until `DOCSTATE_GITHUB_REPO` and a credential are configured. Two modes:

    direct    this side commits, opens one pull request per run and merges it
              (the credential needs contents + pull_requests write)
    dispatch  the credential may only start workflows: the repository's own
              workflow fetches /api/repo-sync/pending and does the writing;
              the files coming back through /api/import acknowledge it

Run `docstate.integrations.github.repo_sync.run_once` from a cron job."""
