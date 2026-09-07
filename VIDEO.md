# Demo video — shot list

**Target 4:40, hard ceiling 5:00. No camera, no voice-over.** Every line of meaning is an
on-screen caption. Screen recording only: a terminal and a browser.

Record at 1920×1080. Terminal 110 columns, 16 pt font, dark theme, `NO_COLOR` unset.
Captions: bottom third, one line, sans-serif, ~40 px, up 0.4 s / hold / down 0.3 s.

Two real runs are already captured in `examples/` if a live take goes wrong. Prefer the
live take: judges can tell.

---

## Before recording

```bash
lms server start
lms load qwen/qwen3.6-35b-a3b --context-length 65536
cd driftcheck && source .venv/bin/activate
clear
```

Browser tabs open and ready, no other tabs:
1. `https://github.com/ScrollPrize/villa/issues/1321`
2. `https://github.com/ScrollPrize/villa/pull/1387` — the description, scrolled to the
   four-row table whose last column is **disclosed before?**
3. `https://github.com/ScrollPrize/villa/pull/1387/files`
4. `https://github.com/ScrollPrize/villa/pull/1440`

---

## 0:00 – 0:22 · The problem

**Shot.** Browser, PR #1387 header. Green *Merged* badge, "Fixes #1321" visible.
Scroll slowly through the Files-changed tab so seven filenames pass by.

> A merged PR. Tests green, reviewer approved, shipped.

> It says it fixes issue #1321.

> Nothing here tells you whether it actually did — or what else it changed.

## 0:22 – 0:48 · What the issue asked for

**Shot.** Browser, issue #1321. Hold on the four-row table (`vc_transform_geom`,
`vc_tifxyz -r 90`, `vc_tifxyz_trim`, `vc_flatten`). Highlight the two ⚠ rows.

> The issue names four tools and asks for two of them to be fixed.

> Remember those four names.

## 0:48 – 1:12 · The architecture

**Shot.** Full-screen `docs/architecture.svg`. Reveal left to right, ~4 s per stage.

> Three Strands agents. What matters is what each one is denied.

> The planner reads the issue and writes the acceptance criteria. It never sees the diff.

> One reviewer per changed file, run in parallel. Each sees one file, so nothing hides in
> the noise.

> The synthesizer calls the verdict, and can send a file back to a reviewer.

> The model is local. No cloud account, no API key.

## 1:12 – 1:25 · The command

**Shot.** Terminal, empty. Type it live at a readable speed.

```bash
driftcheck 1387 --repo ScrollPrize/villa --worktree ~/repos/villa --concurrency 7
```

> One command. GitHub through the gh CLI you already have.

## 1:25 – 2:30 · The run

**Shot.** Terminal. Progress lines appear:
`· issue #1321 → planner` … `· 4 criteria → 7 reviewers` … `· synthesizing`.

Speed the recording to **3×** here. Put `3× speed` as a small persistent corner label —
say it, do not hide it. Real elapsed time is about 3 min 25 s.

> The planner reads issue #1321 and extracts the acceptance criteria.

> Seven reviewer sub-agents, one per changed file, running against a 35B model on this
> laptop.

> `3× speed` — the real run is about three and a half minutes.

## 2:30 – 3:00 · The verdicts

**Shot.** Back to 1× as the report paints. Hold on the criteria block.

> Four criteria, every one met, each with the hunk that satisfies it.

Scroll slowly so all four evidence lines pass.

> On the question it was asked, this PR is clean.

## 3:00 – 3:35 · The finding

**Shot.** Hold on the silent-changes block. Highlight `vc_straighten.cpp`.

> This is the part a linter cannot do.

> `vc_straighten` is not one of the four tools in the issue. Neither is `vc_project_tifxyz`.

**Cut to browser**, PR #1387 → Files changed → `vc_straighten.cpp`. The hunk is on screen:
`- meta.erase("bbox")` replaced by the `bbox_of_valid_points` block.

> Its metadata output changed anyway. From always erasing `bbox` to recomputing it.

> Not a bug. A behaviour change nobody asked for, in a tool the issue never mentioned.

## 3:35 – 4:05 · The proof

**Shot.** Cut to tab 2, the PR description. Hold on the four-row table. Highlight the last
column, then the two rows reading **no** — `vc_straighten.cpp` and `vc_project_tifxyz.cpp`.

> This PR's author was unusually careful, and wrote down the same two files.

> Same two, and nothing else.

**Split screen**: that table on the left, the terminal's silent-changes block on the right.

> DriftCheck never reads a PR description. The planner gets the issue, each reviewer gets
> one file's diff.

> It reconstructed both from the diff alone.

*(Frame it exactly this way. The claim on screen is that the two lists match, and both
lists are in the same frame.)*

## 4:05 – 4:30 · The control

**Shot.** Terminal, `clear`, then run (or paste `examples/villa-pr-1440.txt`):

```bash
driftcheck 1440 --repo ScrollPrize/villa --worktree ~/repos/villa
```

Jump-cut past the wait. Hold on the footer line `none found — the diff stayed inside what
the issue asked for`.

> A different merged PR from the same repo.

> Nothing silent. A tool that flags everything is worth nothing.

## 4:30 – 4:45 · Close

**Shot.** Split screen: `pytest` output on the left, repo root on the right.

```bash
pytest -q      # 43 passed
```

> 43 tests, no network, no model. Including a PR that closes an issue it does not address,
> and an empty diff that must never come back "met".

> Local model, Apache-2.0, one file of glue per stage.

**Final card.** `DriftCheck` — `github.com/dud8/driftcheck` — hold 3 s.

---

## Rules for the edit

- Every claim on screen is visible in the same frame. No cutaway to a slide that asserts a
  finding the terminal did not print.
- Never speed the report itself. Speed only the waiting.
- Do not cut around a failure. If a take produces a different verdict, use that take and
  change the captions — the tool is non-deterministic and the judges know it. If a take
  marks a criterion unaddressed, say so and point at the evidence line; do not reshoot for
  a cleaner number.
- Silence is fine. There is no music bed and no voice-over to sync to.
