# Changelog

All notable changes to spc-md-monitor are documented here.

---

## [1.0.0] - 2026-03-07

### Initial release
- Polls SPC Mesoscale Discussion RSS feed (`spcmdrss.xml`) every 2 minutes
- State-based text matching using negative lookahead/lookbehind regex to correctly handle slash-delimited state abbreviations in SPC text products (e.g. `WESTERN/CENTRAL AR`)
- Searches MD title, ATTN line, CONCERNING line, and full discussion text for state matches
- Amber Discord embeds with direct link to full SPC discussion page
- Startup active MD check — posts full embeds for any active matching MDs on restart, bypassing seen cache
- Cache pruning — expired MD IDs removed from `seen_mds.json` on each poll cycle
- Graceful shutdown notification on SIGINT/SIGTERM
- No external dependencies beyond `requests` — XML parsing via Python standard library
