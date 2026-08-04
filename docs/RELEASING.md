# Releasing neterse

The release pipeline is automated (`.github/workflows/release.yml`); the
steps below are the human parts. Distribution, import, and CLI are all
**`neterse`**.

## One-time setup (before the first release)

1. **PyPI Trusted Publisher.** On pypi.org, create the *pending publisher*
   for the project name `neterse`:
   - Owner: `pcDamasceno` · Repository: `neterse`
   - Workflow: `release.yml` · Environment: `pypi`
2. **GitHub environment.** Create the `pypi` environment in the repo
   settings (Settings → Environments); optionally require reviewers on it
   — that makes every publish a click-to-approve.
3. No API tokens are stored anywhere; Trusted Publishing uses the
   workflow's OIDC identity (`permissions: id-token: write`).

## Per release

1. Bump the version in **both** places (they must stay in lockstep;
   the workflow refuses a mismatched tag):
   - `neterse/__init__.py` → `__version__`
   - `pyproject.toml` → `version`
2. Update `CHANGELOG.md`; record any baseline decisions in
   `docs/DESIGN.md` (byte-parity or token-baseline changes).
3. Commit, push, wait for CI green (tests + token-savings job).
4. Tag and push the tag:

   ```bash
   git tag v0.1.0 && git push origin v0.1.0
   ```

   The workflow builds sdist+wheel, verifies tag == version, smoke-tests
   the wheel (import, `neterse --version`, zero-dep guard), and publishes.
5. Verify: `pip install neterse==<version>` in a clean venv;
   `python -c "import neterse; print(neterse.__version__)"`.

## The name

The natural name `terse` is occupied on PyPI by an unrelated package
abandoned in 2019. The project's working names were `terse` (import) /
`terse-net` (distribution) with a PEP 541 transfer as a long-shot plan;
before the first publish it was renamed **`neterse`** ("network terse",
free on PyPI — verified 2026-08-03) so distribution, import, and CLI
share one name and no PEP 541 process is needed. Nothing was ever
published under the old names.
