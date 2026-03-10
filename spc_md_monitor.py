"""
SPC Mesoscale Discussion Monitor
----------------------------------
Polls the Storm Prediction Center's MD feed every POLL_INTERVAL seconds
and posts a Discord notification when a new Mesoscale Discussion is issued
affecting any of the configured monitored states.

MDs are informational outlooks issued by the SPC ahead of potential watch
or warning issuance. They are not distributed through the NWS alerts API
and require a separate polling mechanism.

SPC MD RSS feed: https://www.spc.noaa.gov/products/spcmdrss.xml
"""

import requests
import json
import re
import time
import xml.etree.ElementTree as ET
import signal
import sys
from datetime import datetime, timezone

# ─────────────────────────────────────────
#  CONFIGURATION  —  edit these values
# ─────────────────────────────────────────
DISCORD_WEBHOOK  = "YOUR_DISCORD_WEBHOOK_URL_HERE"
CACHE_FILE       = r"C:\nws-realtime-alerts\seen_mds.json"

POLL_INTERVAL    = 120   # seconds between feed checks

# States to monitor — MD text is checked for these strings
MONITORED_STATES = [
    "Arkansas",
    "Tennessee",
    "Mississippi",
]

# Also match common abbreviations used in SPC text products
STATE_ABBREVIATIONS = {
    "Arkansas":    ["Arkansas",    "AR"],
    "Tennessee":   ["Tennessee",   "TN"],
    "Mississippi": ["Mississippi", "MS"],
}

SPC_MD_RSS     = "https://www.spc.noaa.gov/products/spcmdrss.xml"
SPC_MD_BASE    = "https://www.spc.noaa.gov/products/md/"
USER_AGENT     = "NOC-MDMonitor/1.0 (github.com/ODST-Aaron/spc-md-monitor)"

HEADERS = {"User-Agent": USER_AGENT}

# ─────────────────────────────────────────
#  EMBED COLORS
# ─────────────────────────────────────────
# MDs use a single amber color — they are always pre-watch informational
MD_COLOR    = 0xFFAA00   # Amber
ON_COLOR    = 0x00CC44   # Green  (startup)
OFF_COLOR   = 0x888888   # Grey   (shutdown)

# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────
def load_json(path: str, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: str, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def format_rfc2822(date_str: str) -> str:
    """Parse RSS pubDate (RFC 2822) to a readable string."""
    from email.utils import parsedate_to_datetime
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.strftime("%b %d %I:%M %p UTC")
    except Exception:
        return date_str or "Unknown"


def format_time_utc(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%b %d %I:%M %p UTC")
    except Exception:
        return iso_str or "Unknown"


def states_in_text(text: str) -> list[str]:
    """
    Return a list of monitored states found in the MD text.
    Checks both full state names and two-letter abbreviations.

    SPC MD text uses formats like:
      "WESTERN/CENTRAL AR INTO..."   — slash adjacent to abbrev
      "PARTS OF AR..."               — space before abbrev
      "AR INTO TX..."                — abbrev at start of segment

    Standard \b word boundaries don't treat '/' as a separator,
    so we use a negative lookbehind/lookahead for alpha characters
    instead, which correctly handles slash-delimited tokens.
    """
    found = []
    text_upper = text.upper()
    for state, terms in STATE_ABBREVIATIONS.items():
        for term in terms:
            if len(term) == 2:
                # Match 2-letter abbrev not immediately preceded or
                # followed by another letter (handles slash, space, dot, etc.)
                pattern = rf'(?<![A-Z]){term}(?![A-Z])'
                if re.search(pattern, text_upper):
                    found.append(state)
                    break
            else:
                if term.upper() in text_upper:
                    found.append(state)
                    break
    return sorted(set(found))



# ─────────────────────────────────────────
#  SPC FEED
# ─────────────────────────────────────────
def fetch_md_feed() -> list:
    """
    Fetch and parse the SPC Mesoscale Discussion RSS feed.

    Feed URL: https://www.spc.noaa.gov/products/spcmdrss.xml
    Returns a list of dicts with keys: mdnum, title, attn, concern, issue,
    expire, discussion, link.

    When no MDs are active the feed contains a single placeholder item —
    these are filtered out automatically.
    """
    try:
        resp = requests.get(SPC_MD_RSS, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except requests.exceptions.RequestException as e:
        print(f"  ✗ SPC feed fetch error: {e}")
        return []
    except ET.ParseError as e:
        print(f"  ✗ SPC feed parse error: {e}")
        return []

    mds = []

    for item in root.findall(".//item"):
        title       = (item.findtext("title")       or "").strip()
        link        = (item.findtext("link")         or "").strip()
        description = (item.findtext("description") or "").strip()

        # Skip the "no active MDs" placeholder item
        if "No Mesoscale Discussions are in effect" in title:
            continue
        if "No Mesoscale Discussions are in effect" in description:
            continue

        # Extract MD number — RSS title is "SPC MD 0042" or "Mesoscale Discussion 0042"
        md_num = ""
        m = re.search(r"(?:SPC MD|Mesoscale Discussion)\s+(\d+)", title, re.IGNORECASE)
        if m:
            md_num = m.group(1).lstrip("0") or "0"

        # Strip HTML tags from description
        clean_desc = re.sub(r"<[^>]+>", " ", description).strip()
        clean_desc = re.sub(r"\s+", " ", clean_desc)

        # Extract ATTN and CONCERNING lines
        attn    = ""
        concern = ""
        attn_m  = re.search(r"ATTN[\s\.\-]+([^\n\.]{5,120})",  clean_desc, re.IGNORECASE)
        conc_m  = re.search(r"CONCERNING[\s\.\-]+([^\n\.]{5,200})", clean_desc, re.IGNORECASE)
        if attn_m:
            attn    = attn_m.group(1).strip()
        if conc_m:
            concern = conc_m.group(1).strip()

        pub_date = (item.findtext("pubDate") or "").strip()
        mds.append({
            "mdnum":      md_num,
            "title":      title,
            "attn":       attn,
            "concern":    concern,
            "issue":      pub_date,
            "expire":     "",
            "discussion": clean_desc,
            "link":       link,
        })

    return mds


def build_md_url(md_num: int | str, link: str = "") -> str:
    """
    Return the SPC HTML URL for this MD.
    Prefers the direct link from the RSS item; falls back to constructing it.
    """
    if link and link.startswith("http"):
        return link
    return f"{SPC_MD_BASE}md{str(md_num).zfill(4)}.html"


# ─────────────────────────────────────────
#  DISCORD
# ─────────────────────────────────────────
def post_embed(embed: dict) -> bool:
    try:
        resp = requests.post(
            DISCORD_WEBHOOK,
            json={"embeds": [embed]},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"  ✗ Discord error: {e}")
        return False


def send_startup():
    state_list = ", ".join(MONITORED_STATES)
    embed = {
        "title":       "🟢  SPC Mesoscale Discussion Monitor — Started",
        "description": (
            f"Service is **online**.\n"
            f"Polling SPC MD feed every **{POLL_INTERVAL // 60} minutes**.\n\n"
            f"**Monitored states:**\n{state_list}"
        ),
        "color":     ON_COLOR,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer":    {"text": "SPC Mesoscale Discussion Monitor"},
    }
    post_embed(embed)
    print("✓ Startup notification sent")


def send_shutdown():
    embed = {
        "title":       "⛔  SPC Mesoscale Discussion Monitor — Stopped",
        "description": "Service has been **shut down**. No further MD notifications will be sent until restarted.",
        "color":       OFF_COLOR,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "footer":      {"text": "SPC Mesoscale Discussion Monitor"},
    }
    post_embed(embed)
    print("✓ Shutdown notification sent")


def send_md_alert(md: dict, matched_states: list[str]):
    """Post a Discord embed for a new Mesoscale Discussion."""
    md_num    = md.get("mdnum", "????")
    attn      = md.get("attn", "").strip()
    concern   = md.get("concern", "").strip()
    issue     = format_rfc2822(md.get("issue", ""))
    expire    = md.get("expire", "") or "See full MD"
    md_url    = build_md_url(md_num, md.get("link", ""))

    # Use concern as the headline if available, otherwise fall back to attn
    headline  = concern if concern else attn if attn else "See full discussion for details."

    # Truncate headline if very long
    if len(headline) > 200:
        headline = headline[:197] + "..."

    states_str = ", ".join(matched_states)

    embed = {
        "title":       f"🟠  Mesoscale Discussion #{md_num}",
        "description": f"**{headline}**",
        "url":         md_url,
        "color":       MD_COLOR,
        "fields": [
            {"name": "Affected States", "value": states_str, "inline": True},
            {"name": "Issued",          "value": issue,       "inline": True},
            {"name": "Expires",         "value": expire,      "inline": True},
            {"name": "Full Discussion", "value": f"[View MD #{md_num} on SPC]({md_url})", "inline": False},
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer":    {"text": f"SPC Mesoscale Discussion Monitor  •  MD #{md_num}"},
    }
    post_embed(embed)


def send_startup_active_summary(seen_mds: list) -> list:
    """
    On startup, fetch the SPC feed and post full alert embeds for every
    active MD that matches monitored states — regardless of seen cache.

    The cache is only used to prevent duplicate embeds during the polling
    loop. On restart, the team needs full situational awareness of whatever
    is currently active, so we always post full embeds here and update the
    cache so the polling loop won't re-fire them.
    """
    print("  Checking for MDs already active at startup...")
    mds = fetch_md_feed()
    if not mds:
        print("  No MDs retrieved at startup.")
        return seen_mds

    current_ids = {str(md.get("mdnum", "")) for md in mds if md.get("mdnum")}
    posted = 0

    for md in mds:
        md_num = str(md.get("mdnum", ""))
        if not md_num:
            continue

        search_text = " ".join([
            md.get("title", ""),
            md.get("attn", ""),
            md.get("concern", ""),
            md.get("discussion", ""),
        ])

        matched = states_in_text(search_text)
        if not matched:
            continue

        # Always post full embed at startup — bypass cache check
        send_md_alert(md, matched)
        posted += 1
        print(f"  → Active at startup: MD #{md_num} | {', '.join(matched)}")

        # Add to cache so polling loop won't re-fire it
        if md_num not in seen_mds:
            seen_mds.append(md_num)

    if posted == 0:
        print("  No active MDs affecting monitored states at startup.")

    # Prune stale IDs no longer in the feed
    seen_mds = [i for i in seen_mds if i in current_ids]
    return seen_mds

def main():
    seen_mds = load_json(CACHE_FILE, [])

    # ── Graceful shutdown ──────────────────
    def handle_shutdown(sig, frame):
        print("\n⛔ Shutdown signal received...")
        send_shutdown()
        save_json(CACHE_FILE, seen_mds)
        sys.exit(0)

    signal.signal(signal.SIGINT,  handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    send_startup()

    # Check for MDs already active at startup
    seen_mds = send_startup_active_summary(seen_mds)
    save_json(CACHE_FILE, seen_mds)

    print(f"✓ Monitoring active — polling SPC every {POLL_INTERVAL}s\n")

    while True:
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] Checking SPC MD feed...")

        mds = fetch_md_feed()
        current_ids = set()

        for md in mds:
            md_num = str(md.get("mdnum", ""))
            if not md_num:
                continue

            current_ids.add(md_num)

            if md_num in seen_mds:
                continue

            # Build searchable text
            search_text = " ".join([
                md.get("title", ""),
                md.get("attn", ""),
                md.get("concern", ""),
                md.get("discussion", ""),
            ])

            matched = states_in_text(search_text)
            if not matched:
                continue

            print(f"  → New MD #{md_num} | States: {', '.join(matched)}")
            send_md_alert(md, matched)
            seen_mds.append(md_num)

        # Prune expired MDs from cache
        seen_mds = [i for i in seen_mds if i in current_ids]
        save_json(CACHE_FILE, seen_mds)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
