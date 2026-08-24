# 03: deploys and hosting

## At a glance

```mermaid
flowchart LR
    push["push (main: production, other branches: preview)"] --> ci["deploy-cloudflare.yml"] --> wd["wrangler deploy"] --> worker["Worker and static assets"]
    ci --> verify["verify: version.json, first-screen budget"]
    worker --> browser["the visitor's browser"]
    worker --> ae[("Workers Analytics Engine")]
    run["poles run [region] --stage publish"] --> r2[("R2 bucket on data.polesofremoteness.com")]
    r2 --> browser
```

Two independent paths reach the visitor. The code path is a git push and takes minutes; the data path is a pipeline run on the owner's Mac and takes hours. Neither waits for the other.

## Detailed view

### The code path: a push

```mermaid
flowchart LR
    push["push touching site/**, worker.js, wrangler.jsonc or the workflow"] --> creds["check CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID"]
    creds --> stamp["write site/version.json with the commit"]
    stamp --> deploy["wrangler deploy, plus --env preview off main"]
    deploy --> prod["main: polesofremoteness on polesofremoteness.com and www, dataset poles_views"]
    deploy --> redir["main only, after verify: atokiausia-lietuva, a permanent redirect to /europe/lt"]
    deploy --> prev["other branches: atokiausia-lietuva-preview, dataset poles_preview_views"]
    prod --> ver["verify: poll /version.json until it carries this commit"]
    prev --> ver
    ver --> budget["preview only: first screen under 256 KB compressed"]
```

Production is the top level of `wrangler.jsonc` (`workers_dev` off, the apex and www as custom domains); the redirect worker under `redirect/` deploys from main only, after the production verify, so the old URL never errors. The verify job proves that this commit is live, not that some version of the site is. It polls for up to three minutes, because a new worker version reaches the edges over a few seconds and one edge can answer while another still serves the previous version. The budget step fetches every file the first screen needs and adds up the compressed bytes; `JSON_STRICT` is `1` since 2026-08-23: a data file answered as the SPA fallback fails the run.

Two other workflows guard the same repository and deploy nothing: `pipeline-tests.yml` builds `pipeline/Dockerfile` and runs pytest inside it on any change under `pipeline/`, `docs/`, `CLAUDE.md` or `README.md` (the checkout is mounted into the container as `POLES_REPO_ROOT`, so the doc pins in `pipeline/tests/test_docs_pins.py` run on docs-only commits too), and `site-tests.yml` runs `node --test 'dev/tests/*.test.mjs'` on any change under `site/js/`, `dev/` or `worker.js`.

### What is live

```mermaid
flowchart LR
    browser["browser"] --> workers["Cloudflare Workers"]
    workers --> assets["assets binding, directory ./site"]
    workers -.-> rewriter["page paths only: HTMLRewriter adds meta name=visitor"]
    workers -.-> point["page paths only: one Analytics Engine data point"]
    browser --> r2[("R2 bucket over data.polesofremoteness.com, CORS allowed")]
```

`run_worker_first` in `wrangler.jsonc` sends only the extension-less paths (`/`, `/<region>`, `/<region>/<unit>`) through the worker, so `/css/*`, `/js/*`, `/vendor/*`, `/data/*` and anything with an extension are answered by the assets layer and never count as a view. The data point is eight blobs, in a fixed order that queries address positionally: country, colo, referrer host, browser family, OS family, hostname, landing region, landing unit. No IP, no raw user agent, no cookie, no identifier.

### The data path: a publish

```mermaid
flowchart LR
    mac["poles run [region] --snapshot [date] --stage publish"] --> local["local artefacts under work/[region]/[snapshot]/publish/"]
    local --> s3["upload over the S3 API"]
    s3 --> bucket[("R2 bucket, keys under [region]/[snapshot]/")]
    bucket --> head["HEAD every key, range request every archive"]
    head --> sitejson["write site/data JSON, then commit"]
    sitejson --> push["push, which runs the code path above"]
```

The local part runs before the R2 configuration is read, so a machine without the credentials still builds every artefact and stops with a `PublishError` naming the variables that are missing. The site documents are written only after the verification passed, so `site/data` can never name an object that did not answer.

### Secrets, by name only

Every value lives outside the repository. Nothing here is a value, only a name.

| Path | Name | Where it lives |
|---|---|---|
| code | `CLOUDFLARE_API_TOKEN` | GitHub repository secret |
| code | `CLOUDFLARE_ACCOUNT_ID` | GitHub repository secret |
| data | `POLES_R2_ACCOUNT_ID` | environment variable, the Cloudflare account id |
| data | `POLES_R2_BUCKET` | environment variable, the bucket name |
| data | `POLES_R2_TOKEN_FILE` | environment variable naming a one-line file, mode 600: the Cloudflare API token with R2 admin read and write |
| data | `POLES_R2_ACCESS_KEY_ID_FILE` | environment variable naming a one-line file, mode 600: the S3 access key id |
| data | `POLES_R2_SECRET_FILE` | environment variable naming a one-line file, mode 600: the S3 secret |
| data | `POLES_R2_BASE` | optional environment variable; the managed `r2.dev` domain (otherwise discovered) or a custom domain connected to the bucket |
| data | `POLES_R2_CORS` | optional environment variable; comma-separated CORS origins, default `*` |

Reflects the code at the Stage 6 cutover (2026-08-24).
