<p align="center"><img src="../assets/dirt-logo.png" alt="dirt." width="260"></p>

# DIRT 🔞

**D**IRT is GURT's opt-in section for mature (18+) stuff. It's **off by default** in the CLI, sits behind an "Are you sure?" 18+ gate on the website, and `gurt search -a` skips it.

```sh
gurt dirt on           # asks you to confirm you're 18+
gurt dirt list
gurt install dirt/<name>
gurt dirt off
```

## rules
- 18+ only, and everything here must be legal where you live and clearly labeled
- **nothing involving minors, ever** — instant removal + ban
- no malware, ~~no piracy~~, no non-consensual content
- same recipe rules as `packages/` (no sudo, no `curl | sh`, folder name == pkgname)

It's empty for now — recipes go in `dirt/<name>/GURTBUILD` and get reviewed like any other PR.
