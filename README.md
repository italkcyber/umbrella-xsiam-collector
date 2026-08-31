# ☂️ Umbrella → XSIAM Collector (Without SQS)

![License: MIT](https://img.shields.io/badge/license-MIT-green)
![XSIAM 3.x](https://img.shields.io/badge/Cortex%20XSIAM-3.x-blue)
![Umbrella schema v13](https://img.shields.io/badge/Umbrella%20log%20schema-v13-blue)
![Tests](https://img.shields.io/badge/tests-20%20passing-brightgreen)
![Maintained by iTalkCyber](https://img.shields.io/badge/maintained%20by-iTalkCyber-0C6B70)

**A custom Cortex XSIAM event collector that ingests every Cisco Umbrella log type — DNS,
Secure Web Gateway, Cloud Delivered Firewall, IPS, DLP, IP and admin audit — directly from
the Cisco-managed S3 bucket, by polling it.**

No SQS queue. No S3 bucket of your own. No Lambda, no Terraform, no AWS account.
If Umbrella gave you an `s3://cisco-managed-…` path and a key pair, that is everything
this needs.

> 💡 **Start here → [Deployment Guide](DEPLOYMENT-GUIDE.md)**
> Architecture, phase-by-phase install, a full settings reference, troubleshooting keyed on
> real error strings, and an XQL query library. This page is just the overview.

---

## The problem this solves

Cisco Umbrella exports logs to S3 two ways: a bucket **you** own, or a bucket **Cisco**
manages for you. XSIAM's native Amazon S3 data source only works with the first, because
it is notification-driven — the bucket must publish `s3:ObjectCreated` events to an SQS
queue, and only a bucket's owner can configure that. On a Cisco-managed bucket there is
no queue to create and nothing to subscribe to.

The usual answer is to switch Umbrella to a self-managed bucket and build the SQS
plumbing (Palo Alto ships a [Terraform module](https://github.com/PaloAltoNetworks/terraform-umbrella-s3-to-xsiam-ingestion-module)
for exactly that). This project takes the other road: keep the Cisco-managed bucket, and
replace the notification + queue with a polling loop and a saved cursor.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/architecture-dark.svg">
  <img alt="Umbrella writes gzipped CSV to the Cisco-managed S3 bucket every ten minutes. The Cisco Umbrella S3 Event Collector polls it with ListObjectsV2 using a saved cursor per log type, downloads and parses the files, and POSTs gzipped newline-delimited JSON to the cisco-umbrella-s3 HTTP Collector, which writes the cisco_umbrella_s3_raw dataset that data model rules map into XDM for queries and detections." src="docs/architecture-light.svg" width="100%">
</picture>

**Why events take an indirect route.** XSIAM has a built-in shortcut for integrations to write
events straight into a dataset — a function called `send_events_to_xsiam()`. Palo Alto restricts
it to *system content*: integrations that ship with the platform or come from the official
Marketplace. Anything you upload yourself is *custom content*, and calling it fails with
`command 'getLicenseCustomField' is only available for system content` — the function reads a
licence detail that custom content isn't permitted to see.

So this collector uses XSIAM's other supported entrance: an **HTTP Collector**, a general-purpose
ingestion endpoint you create in the console in about a minute. It hands you a URL and an API key,
and anything that can POST JSON can feed XSIAM through it. No privileged calls, no workaround.

The only cost is bookkeeping: XSIAM credits ingested volume to whatever delivered it, so the
collector's row under Data Sources shows your event counts and the integration's own counter stays
empty. Monitor the collector's row.

## Log type coverage

| Folder | Contents | Requires |
|---|---|---|
| `dnslogs` | Every DNS query + verdict | Any Umbrella licence (highest volume by far) |
| `auditlogs` | Dashboard admin actions | Any licence (written only on change) |
| `proxylogs` | URLs, methods, file hashes, AMP verdicts | SIG / Secure Web Gateway |
| `firewalllogs` / `cloudfirewalllogs` | L3/L4 connections + verdicts | Cloud Delivered Firewall |
| `intrusionlogs` | IPS signature hits | CDFW with IPS |
| `dlplogs` | DLP matches + file detail | Umbrella DLP |
| `iplogs` | IP-layer enforcement sessions | IP-layer enforcement |

## What's in the repo

| File | Purpose |
|---|---|
| **`CiscoUmbrellaS3EventCollector.yml`** | The integration — upload this to XSIAM. |
| **`CiscoUmbrellaS3ModelingRules.xif`** | XDM mapping, one block per Umbrella log type. |
| **[`DEPLOYMENT-GUIDE.md`](DEPLOYMENT-GUIDE.md)** | The deployment guide — architecture, phased install, settings reference, troubleshooting, XQL library. |
| `CiscoUmbrellaS3EventCollector.py` | The collector source, unpacked, for review. |
| `build/` | Rebuilds the uploadable YAML from the source: `python3 build/build.py`. |
| `tests/` | 20 offline tests, zero dependencies: `python3 tests/test_collector.py`. |

## Installing, in one paragraph

Import the `.yml` into XSIAM, create a custom **HTTP Collector** (vendor `cisco`, product
`umbrella_s3`, gzip, JSON), configure an instance with your Umbrella keys and the
collector's URL and key, and — only once data has landed — add the XDM rules. Order
matters and several steps have non-obvious failure modes, so follow the
[Deployment Guide](DEPLOYMENT-GUIDE.md)
rather than improvising; it also covers what to do when something goes wrong.

## Engineering notes

- **The cursor survives Umbrella's random filenames.** Object keys end in a random
  suffix, so a late upload can sort *before* a key already processed — a naive
  "highest key seen" cursor would skip it forever. This one lags 30 minutes and
  de-duplicates the overlap against a 4,000-key ring buffer.
- **State commits after every push**, not at the end of the run, so a run killed
  mid-backfill keeps what it delivered. Delivery is at-least-once; dedupe on `s3_key` +
  row if you need exactness.
- **Runs stop themselves** at a configurable time budget, before the container timeout
  would kill them — long backfills never leave the instance in an error state.
- **A poison event can't wedge a feed.** An event too large for one request is dropped
  with a log line naming its source object rather than blocking the cursor forever.
- **Failed sends are never marked done** — those objects retry next run. Transport
  errors retry with backoff.
- **Nothing unmapped is lost.** Every Umbrella column is queryable on the raw dataset
  whether or not the XDM rules map it.

## Caveats

- Schema v13 column orders were cross-verified against several public parser
  implementations (Elastic, Rapid7, LogRhythm), not Cisco's own docs, which aren't
  machine-readable. The guide has you confirm one real row before trusting field names.
- XDM field availability varies by tenant. Each `.xif` block keeps a conservative core
  live and lists richer fields to enable one at a time; your rule editor's autocomplete
  is the authority.
- XSIAM attributes ingestion volume to the HTTP Collector, not this integration — inherent
  to the custom-content route. Monitor the collector's data-source row.

## Credits

Developed and maintained by **[iTalkCyber](https://github.com/italkcyber)**. 

## Disclaimer

Community project. Not affiliated with, endorsed by, or supported by Cisco or Palo Alto
Networks; all trademarks belong to their owners. No warranty — the collector is one
readable Python file, so review it before running it against production.

## References

- [Enable logging to a Cisco-managed S3 bucket](https://docs.umbrella.com/deployment-umbrella/docs/cisco-managed-s3-bucket)
- [Umbrella log formats and versioning](https://docs.umbrella.com/deployment-umbrella/docs/log-formats-and-versioning)
- [Umbrella S3 key rotation (required every 90 days)](https://www.cisco.com/c/en/us/support/docs/security/secure-access/222844-verify-secure-access-and-umbrella-s3-buc.html)
- [XSIAM event collection integrations](https://xsoar.pan.dev/docs/integrations/event-collectors)

## License

MIT — see [LICENSE](LICENSE).
