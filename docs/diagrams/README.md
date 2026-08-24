# Diagrams: the map, not the territory

Mermaid in markdown: renders on GitHub and in VS Code, diffs with the code. They show how the pieces connect, not every field or flag; the detail lives in `pipeline/README.md`, `docs/EUROPE_SPEC.md` and the code.

| File | What it shows | Audience |
|---|---|---|
| `01-pipeline.md` | the seven stages, what each reads and writes under `work/`, what leaves the machine | pipeline work |
| `02-site-data-flow.md` | what the site loads from R2 and `site/data/`, the URL and hash state, the modules that own each step | site work |
| `03-deploy.md` | what a push to `main` does, what a pipeline publish does, where the live pieces sit | deploys, incidents |

Each file opens with "At a glance" (a handful of boxes) and then the detailed view, and ends with a "Reflects the code at ..." line naming the stage and date it was last checked against the code.

## Legend

Solid arrow: a stage or request in the order shown. Dashed arrow: optional, or only when configured. Cylinder: a file or object store. `[name]`: a placeholder in a path or URL.

## Keeping these current (do not let them drift)

A stale diagram is worse than none. Update the diagram in the same commit as the change:

| If you change | Update |
|---|---|
| a stage name, its order, or what a stage writes (`pipeline/poles/stages.py`, a stage module) | `01-pipeline.md`, and the stage table in `pipeline/README.md` |
| a region config key (`pipeline/regions/*.yaml`, `pipeline/poles/config.py`) | the key table in `pipeline/README.md` |
| what publish uploads or where (`pipeline/poles/publish/`) | `01-pipeline.md` and `02-site-data-flow.md` |
| what the site fetches, the routes or the hash state (`site/js/data.js`, `site/js/router.js`, `site/js/app.js`) | `02-site-data-flow.md` |
| the worker, the CI workflow or the hosting (`worker.js`, `wrangler.jsonc`, `.github/workflows/`) | `03-deploy.md` |

`pipeline/tests/test_docs_pins.py` fails when a stage or a config key is missing from the docs; everything else in this table is on the author.
