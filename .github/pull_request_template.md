<!-- For a new command family, CONTRIBUTING.md is the flow and
     docs/SPECS.md the field reference; scripts/new_spec.py scaffolds
     the file layout. Delete sections that don't apply. -->

## What

<!-- One or two sentences: which family/vendor/surface, and why. -->

## Savings

<!-- Paste the before/after character counts:
       neterse audit tests/fixtures
     (your family's line plus the TOTAL line is plenty). -->

## Checklist

- [ ] Spec YAML **and** the regenerated `neterse/specs/_compiled.py`
      committed together (`python scripts/compile_specs.py`)
- [ ] Fixtures under `tests/fixtures/<platform>/<family>/`:
      `raw.txt` (byte-exact, scrubbed with same-length replacements),
      `commands.txt`, and the golden `expected.txt`
      (`python scripts/update_goldens.py` — eyeball the rendering!)
- [ ] `pytest` green locally
- [ ] Token baseline regenerated if the token job asked
      (`python scripts/update_token_baseline.py`, tiktoken==0.13.0)
- [ ] `dropped_fields` honestly names every data-bearing omission
      (`[]` = lossless); pure noise is not declared
- [ ] For an output change to an EXISTING family: linked issue +
      docs/DESIGN.md decision entry (see CONTRIBUTING.md)
