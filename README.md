# spc-md-monitor

A Python-based SPC Mesoscale Discussion monitor for ISP/NOC environments. Polls the Storm Prediction Center RSS feed and posts Discord notifications when a new Mesoscale Discussion is issued affecting your monitored states.

Designed as a companion to [nws-realtime-alerts](https://github.com/ODST-Aaron/nws-realtime-alerts). MDs are informational outlooks issued by the SPC ahead of potential watch or warning issuance — typically 30 minutes to several hours before a watch is issued. They are not distributed through the NWS alerts API and require a separate polling mechanism.

---

## Features

- **Polls SPC RSS feed** (`spcmdrss.xml`) every 2 minutes
- **State-based matching** — checks MD text for monitored state names and abbreviations, including slash-delimited formats common in SPC text products (e.g. `WESTERN/CENTRAL AR`)
- **Startup active MD check** — posts full embeds for any active MDs affecting monitored states on every restart
- **Amber Discord embeds** visually distinct from NWS warning/watch embeds
- **Direct link** to full SPC discussion page in every embed
- **Graceful shutdown** — posts a shutdown notification on Ctrl+C or SIGTERM
- **Cache pruning** — automatically removes expired MD IDs from cache when they leave the feed

---

## Requirements

```
requests>=2.31.0
```

Install with:
```powershell
pip install requests
```

No other dependencies — XML parsing uses Python's built-in `xml.etree.ElementTree`.

---

## Setup

### 1. Clone the repository

```powershell
git clone https://github.com/ODST-Aaron/spc-md-monitor.git
cd spc-md-monitor
```

### 2. Configure the script

Edit the configuration block at the top of `spc_md_monitor.py`:

```python
DISCORD_WEBHOOK  = "YOUR_DISCORD_WEBHOOK_URL_HERE"
CACHE_FILE       = r"C:\spc-md-monitor\seen_mds.json"

POLL_INTERVAL    = 120   # seconds between feed checks

MONITORED_STATES = [
    "Arkansas",
    "Tennessee",
    "Mississippi",
]
```

Update `MONITORED_STATES` to match the states relevant to your network footprint.

### 3. Run

```powershell
py -3.12 spc_md_monitor.py
```

---

## Discord Embed Format

When a relevant MD is issued:

- **Title:** `🟠  Mesoscale Discussion #XXXX` (links to SPC page)
- **Description:** Concern/headline from the MD
- **Fields:** Affected states, issued time, expiry, link to full discussion

Amber color (`#FFAA00`) is used for all MD embeds to distinguish them from NWS warning/watch tiers.

---

## File Reference

| File | Description |
|------|-------------|
| `spc_md_monitor.py` | Main monitor script |
| `seen_mds.json` | MD number cache — **excluded from git** |

---

## Notes

- The SPC RSS feed (`https://www.spc.noaa.gov/products/spcmdrss.xml`) does not include a `Last-Modified` header, so polling is interval-based rather than change-driven.
- When the feed is quiet, it contains a single placeholder item — "No Mesoscale Discussions are in effect" — which is filtered out automatically.
- MD expiry times are not included in the RSS feed. Each embed links directly to the SPC discussion page for full details including expiry.
- `seen_mds.json` is pruned on each poll to remove IDs no longer present in the feed (i.e. expired MDs). Delete it if you want active MDs to re-fire on next startup.

---

## Related

- [nws-realtime-alerts](https://github.com/ODST-Aaron/nws-realtime-alerts) — Real-time NWS warning/watch/advisory monitor
