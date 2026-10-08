# Official API and runtime notes

Reviewed 2026-10-08. Public documentation is authoritative for the target account/version.

## [Hetzner Cloud API](https://docs.hetzner.cloud/reference/cloud)

Bearer project tokens, paginated resources and asynchronous action responses.

## Boundaries

Python 3.10+. Set `HCLOUD_TOKEN` through your secret manager (legacy `HETZNER_ADMIN_TOKEN` also accepted). Optional `hcloud` CLI; otherwise use `--backend api`. Credentials are never read from a repository config file.

Snapshots include infrastructure metadata and IPs; keep them private. Default commands sync inventory; `--no-sync` reads cached data. No automatic project selection, action polling or cost quote. Creation defaults are conveniences, not a guarantee of stock or price.

HTTP helpers do not follow redirects or automatically retry writes. A timeout can mean an unknown outcome; inspect the target before retrying. Secret-field redaction is defense in depth, not a guarantee that arbitrary free text is safe to publish.
