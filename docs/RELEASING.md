# Releasing terse-net

The release pipeline is automated (`.github/workflows/release.yml`); the
steps below are the human parts. The distribution is **`terse-net`**, the
import is **`terse`** (decision 1).

## One-time setup (before the first release)

1. **PyPI Trusted Publisher.** On pypi.org, create the *pending publisher*
   for the project name `terse-net`:
   - Owner: `pcDamasceno` · Repository: `terse`
   - Workflow: `release.yml` · Environment: `pypi`
2. **GitHub environment.** Create the `pypi` environment in the repo
   settings (Settings → Environments); optionally require reviewers on it
   — that makes every publish a click-to-approve.
3. No API tokens are stored anywhere; Trusted Publishing uses the
   workflow's OIDC identity (`permissions: id-token: write`).

## Per release

1. Bump the version in **both** places (they must stay in lockstep;
   the workflow refuses a mismatched tag):
   - `terse/__init__.py` → `__version__`
   - `pyproject.toml` → `version`
2. Update `CHANGELOG.md`; record any baseline decisions in
   `docs/DESIGN.md` (byte-parity or token-baseline changes).
3. Commit, push, wait for CI green (tests + token-savings job).
4. Tag and push the tag:

   ```bash
   git tag v0.4.0 && git push origin v0.4.0
   ```

   The workflow builds sdist+wheel, verifies tag == version, smoke-tests
   the wheel (import, `terse --version`, zero-dep guard), and publishes.
5. Verify: `pip install terse-net==<version>` in a clean venv;
   `python -c "import terse; print(terse.__version__)"`.

## The `terse` name (PEP 541)

PyPI `terse` is occupied by an unrelated package abandoned in 2019.
Reclaiming it is a [PEP 541](https://peps.python.org/pep-0541/) transfer
request: open an issue on [pypi/support](https://github.com/pypi/support)
with the `PEP 541` template *after* `terse-net` is published (the request
needs a live project to transfer to). Until/unless granted, the
install name stays `terse-net`; nothing else changes (decision 1).
