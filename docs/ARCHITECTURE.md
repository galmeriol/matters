# Matters — architecture

## The idea in one sentence

Turn work recorded **in time order** (agent sessions: a journal) into
understanding **organised by subject** (a ledger), **on demand**, with
every piece **traceable to its source**.

Pacioli's journal records what happened; the ledger tells you where you stand.
Matters is the ledger for agent work.

## Who it is for

The first real user is **a developer running several local agents**: restarting
work, reviewing what agents did, settling how they want things done. Other
readers (a lead checking work against a brief, someone writing a weekly status)
want the same things from other sources and in other shapes; they change
*plugins* (a Source, a rendering), never the core, and none of them is built for
until someone needs it.

### Core needs

| # | Need | Meaning | Where it lives now |
| --- | --- | --- | --- |
| N1 | **Gather** | Read sessions from many tools; adding a tool must be cheap | `Source` role; Claude Code today |
| N2 | **Read well** | A session is mostly text: make it legible, fold what is noise | The session page |
| N3 | **Find** | Any word, in what was asked, answered or done, across every session | Search |
| N4 | **Trace** | Everything opens at its turn and source line; things seen twice link to each other | Every page |
| N5 | **Pick up** | Where a project stands and what was left unfinished | The project brief, `matters brief` |
| N6 | **Settle** | What you keep telling assistants, written down once and vetted | Knowledge |
| N7 | **Stay private** | Local, read-only against sources; nothing leaves unless you choose | Only knowledge extraction calls a model |

## Principles

1. **Domain in the middle, tools at the edges.** The core knows Sessions,
   turns, briefs and knowledge. It does not know Claude, Codex, SQLite, LLMs or HTML.
2. **Traceability is an invariant, not a feature.** Every Entry and knowledge item carries
   a `SourceRef`. Anything that can't point at its source does not go on a page.
3. **Legibility is the product.** It is a text product: how a turn reads, how
   a hit is shown, how one page leads to the next matter more than any feature.
4. **Read-only and local by default** (N6).
5. **Defer every decision until a requirement forces it.** Each deferred
   decision has a named trigger below. Until it fires, the simplest thing wins.
6. **Refactor first, then extend.** When a requirement doesn't fit, first change
   the code (with tests still passing) so it does fit, then add the requirement.

## The pipeline

```text
 files on disk        journal                     pages (all deterministic, local)
┌──────────┐     ┌──────────────────┐     ┌────────────────────────────────────────────┐
│ Source   │ ──▶ │ Session          │ ──▶ │ session page  turns, timeline, cross-links │
│ (role)   │     │  └ Entry         │     │ search        asks · answers · work        │
│ claude-  │     │    kind,text,ref │     │ brief         where it stands, what's open │
│ code     │     │    └ ToolCall    │     └────────────────────────────────────────────┘
└──────────┘     │  └ turns → Turn  │
                 │    ask, steps,   │      on demand, through a model:
                 │    answer, work  │     ┌────────────┐   ┌───────────┐   ┌───────────┐
                 └──────────────────┘ ──▶ │ Transcript │──▶│ Extractor │──▶│ Knowledge │──▶ PREFERENCES.md
                                          │ redacted,  │   │ (role)    │   │ vetted,   │    FACTS.md
                     CLAUDE.md, AGENTS.md │ + already  │   │ read,edit │   │ cites     │
                     already written ───▶ │   written  │   └───────────┘   │ turns     │
                                          └────────────┘                   └───────────┘
```

Everything you read is computed from the journal on each request, locally and
for free. The one judgment call, *what in these sessions is a durable preference
or fact*, uses a model, only when you ask, and only for the sessions you pick.

## The viewer's UX, and why

Measured on real sessions: of every 20 content blocks, about one is what the
human typed. The rest is tool calls, tool results and thinking. So the page
is built around **turns**:

- **Ask**: what you typed, prominent, behind a solid ink rule. What came with
  it keeps its own shape (icons are a small inline SVG set): open-file and
  selection **chips**, pasted text as an inline **folded card** where it was
  pasted, attached **images** as click-to-zoom thumbnails. Tool-injected
  context (system reminders) gets a *dashed* border: solid means you sent
  it, dashed means the tool added it. Messages sent while Claude was working
  are asks too, chipped "Sent while Claude was working".
- **Answer**: the assistant's last text in the turn, shown open and rendered
  as Markdown in a reading serif. It's what you actually read at the time.
  Project-relative links (`[a.py:42](src/a.py#L42)`) open in VS Code at the line.
  Prose stops near 68 characters a line (hyphenated, `text-wrap: pretty`);
  code, tables and diagrams keep the full column. Fenced code is highlighted
  *in ink* by Pygments (weight and slant, no hue), labelled with its language,
  and copyable.
- **Turn margin**: when the turn started, how long the assistant worked on it,
  and the files it changed (each opens in the editor).
- **Became knowledge**: under your ask, the preferences and facts that cite this
  turn (accepted or waiting), each linking to its row on the knowledge page.
- **Work**: everything in between, folded into one line ("22 steps · Bash ×10 ·
  Write ×4 · 1 failed"). Unfolded, each tool reads in its own shape: edits as
  diffs, Bash as `$ command` + output, Read/Grep/Web as a one-line target.
  Thinking stays folded.
- **Events**: slash commands (with their output, folded), interruptions and
  background-task notices sit in the turn as one-line rows, never in the fold.
- **Rail, always there**: every page keeps all sessions on the left, grouped
  by project, most recently active first, set like a book's contents: each
  project a heading over a rule, with how many sessions it holds; each session
  a line with a dotted leader to its work time where a page number would be,
  its day below. The one you are reading opens into a card lifted off the rail:
  its day and asks, and a barcode of when work happened in it. It is set in the
  interface's sans on a tone of its own, never the reading face, so it never
  passes for the session beside it. A project's name opens its brief; its
  chevron folds it. A project starts open while it has a session from the last
  week (or the one you are reading); a fold you set is kept in the browser and
  wins, applied by a script right after the rail so it never flashes. A small
  ring marks a session that ended unfinished. Each session's timeline is drawn
  once while its file stays the same, so the work times cost nothing after the
  first page. Typing filters it instantly, unfolding projects with a match;
  Enter searches all text. `[`/`]`
  move between sessions, `j`/`k` between turns, `e` unfolds all work, `t`
  shows the timeline lanes, `n`/`N` step through search matches, `/` focuses
  the filter. `/` opens the most recent session. A turn index sits on the
  right on wide screens, with every edited file and the turns that changed
  it; under 56rem the rail becomes a drawer.
- **A session's header answers in order**: how it ended (a sentence, linked to
  the turn), then its figures, each labelled and said in words and linking to
  where it is taken apart, then where the time went, with how to read the lanes.
- **Long sessions fold after their first turns.** Past 8 turns, only the first
  three are open; every turn after them folds into chapters of ten, one line each
  (when, files changed, knowledge). Everything stays on the page, so links, find in page and
  search marks still reach a folded turn. The index is two tabs, turns and files,
  with the files as a tree of their folders.
- **Source**: every block has a `line N` link (shown on hover) that opens the
  raw session in VS Code.
- **Resume**: a copyable `cd <project> && claude --resume <id>`.

**Look: e-ink broadsheet.** Ink on neutral paper, hairline and double rules,
square corners, no shadows, inverse video for "you are here", a single ink-blue
accent reserved for links. Three faces: Charter for reading (ships with macOS,
drawn for low-resolution output), the system sans for interface, the system
mono for code; nothing is downloaded.

**Turn order.** A session reads oldest first or newest first. The settings menu
sets the order for every session; the switch above a session's turns sets it for
that session alone, and that session keeps it whatever the default becomes
(picking the default again lets it follow the default). The server draws the
order, so folding follows it: three turns open at the end you read from, the
rest folded in tens away from it, and the index numbered the same way. Both
choices live in the browser as cookies (`matters-order`, and `matters-turns`
for the sessions set on their own, the latest picks that fit in 4 KB), not
`localStorage`, because the server needs them to draw the page. A **Newest
turn** button stays in sight while that turn is out of view, and `G` goes
there.

**Themes.** Paper (the look above) is the default; Warm (cream paper with a faint
grain, ink blue, hairline rules, a tint for "you are here" instead of a black
block) and Library (the same paper, a deep green rail, teal) are the others,
each in Auto, Light or Dark, chosen from the sliders button at the top of the
rail and kept in the browser (`localStorage`; a script in the head applies it
before the page paints). A theme is one block of tokens, every colour a
`light-dark()` pair, so the mode is just `color-scheme`. What a colour means
holds in every theme: `--err` a failure, `--live` something running,
`--add-ink`/`--del-ink` a diff, `--mark` a search hit, `--sel-bg` where you are;
accent and timeline lanes stay clear of those hues (no green accent: it would
read as "running", and red on green is the pair colour-blind readers lose).
`tests/test_palette.py` checks every theme in both modes: text at WCAG AAA
(7:1), lanes and the running pulse at 3:1, and those meanings apart. The
lanes can be shaded by token use (`--lane`, `--lane-mid`, `--lane-lo`: one
hue, darker for more, the lightest still at 3:1; none is hatched), a choice
kept in the browser and applied before paint like the theme.

It's server-rendered HTML from the standard library (`wsgiref`, `html`,
`difflib`) plus `markdown-it-py` (CommonMark, raw HTML escaped). Folding uses `<details>`, so the page works without JavaScript; the
small script only adds keys and copy. It binds to 127.0.0.1, escapes
everything, and a CSP blocks all outside loads. Each request re-asks the
source, which re-reads only files whose mtime changed: reload to see a
running session grow.

## Interfaces (roles)

A role is a `typing.Protocol`: players conform by shape, not inheritance.
`mypy --strict` checks every player statically, and `tests/test_roles.py`
checks every player at runtime, **fakes included**.

| Role | Method | Players now | Players later | Earned by |
| --- | --- | --- | --- | --- |
| **Source** | `sessions(project: Path \| None = None) -> list[Session]` (None = all) | `ClaudeCode` (mtime-cached per file) | Codex, Copilot (JSON), Cursor (SQLite, read-only), Gemini, Aider, ChatGPT export | Iteration 2: second provider. Codex since parked (Claude only for now); the seam stays |
| **ToolView** | `summary() -> str`, `body() -> str` (HTML) | Bash, Read, Edit, MultiEdit, Write, Grep/Glob, Web, Agent; generic default | One per tool that reads badly in the generic view | Iteration 5: each tool needs its own shape on the page. Self-registering subclasses, picked by `ToolView.for_` |
| **Provider** | `name`, `model`, `setup_hint`, `configured()`, `complete_json(system, user, schema, max_tokens) -> Completion(data, usage)`; raises `ModelError` (see `errors.py`) | `ClaudeCodeProvider` (headless `claude -p`), `FakeProvider` in tests; `llm.registry.from_env()` sets it up | None planned: users need nothing but Claude Code | Iteration 9: Gemini as well as Claude; iteration 12: only headless Claude Code |
| **Extractor** | `model`, `extract(transcript, known, projects) -> Extracted` | `LlmExtractor(provider)` (read pass + edit pass), `FakeExtractor` in tests | Cheaper per-segment reading when selections grow | Knowledge |
| Store | `fetch(key) / save(key, value)` | `KnowledgeStore` (SQLite) for knowledge only; sessions use the in-memory mtime cache (a full scan takes ~0.2 s) | SQLite + FTS5 for sessions | Trigger: a full scan or a search takes over ~1 s |

Retired in iteration 11, with the features they served: **Distiller**,
**Tagger** and **Mapper**, and the never-built Scope and Renderer.

Values (frozen, slotted dataclasses): `SourceRef(path, line)`,
`ToolCall(name, input, result, is_error)`,
`Entry(kind: ask|text|thinking|tool|…, text, ref, tool)` with `failed` / `changed`,
`Turn(number, ask, steps)` with `answer` / `work` / `tool_counts` / `label`,
`AgentRun` with `state`,
`Session(id, provider, project, entries, title, started_at, ended_at, agents)` with
`turns`, `edits_by_file()`, `agents_in(turn)`, `wall_seconds`.

## How the code reads

The code is meant to read as the mental model of the thing it handles, top to
bottom, with the nouns doing the work:

- **Making and converting are methods.** A thing is made from what it comes
  from (`Turn.from_entries`, `Tokens.from_usage`, `TaskList.from_session`,
  `Brief.of(sessions, project)`, `Stack.of`, `Timeline.of`, `Item.from_row`,
  `Transcript.build`) and turned into what it goes to (`Brief.to_markdown()`,
  `Evidence.to_json`, `ModelEntry.to_draft`, a view's `to_html()`). Small derived
  facts are properties (`Entry.changed`, `Turn.label`, `AgentRun.state`).
- **The standard library first**: `Counter`, `itertools.pairwise`,
  `functools.cached_property`, `dataclasses.replace`, `contextlib.suppress`.
- **Pages are view objects.** `SessionPage` holds what the page needs (cached
  once) and hands it to `Glance` / `Figure`, `TurnView`, `IndexPart` and
  `FileTree`, each with `to_html()`. `RunView` is a subagent run on any page.
- **Errors are few and named by what went wrong for the user** (`errors.py`):
  `ModelError` (the model call failed, timed out, refused or answered badly),
  `SettingError` (an environment setting is wrong), `DataError` (stored data
  doesn't read back). All derive from `MattersError`, whose message is written
  for the person reading it; the job page shows it as is. Nothing outside the
  tests uses `assert` for control flow.

Where things live:

| Module | What it holds |
| --- | --- |
| `session.py` | The journal every source produces: `Session`, `Turn`, `Entry`, `ToolCall`, `AgentRun` |
| `sources/claude_code.py` | The Claude Code `Source`: which files are sessions, cached by mtime |
| `sources/claude_records.py` | One JSONL file read into entries: `Record`, `Journal`, tool results |
| `sources/claude_agents.py` | Subagent files paired with the calls that started them: `AgentFile`, `Evidence` |
| `clock.py`, `errors.py` | Reading times (`moment`, `seconds_between`); the exception family |
| `tasks.py`, `changes.py`, `timeline.py` | Derived from the journal: the checklist, a file's stack, where the time went |
| `brief.py`, `search.py`, `transcript.py` | A project's brief, search results, the text a model reads |
| `knowledge/` | Items and their store, the extractor's two passes, export |
| `web/frame.py`, `web/text.py` | What every page shares (document, rail); words and numbers as pages print them |
| `web/session_page.py`, `web/work_views.py`, `web/tool_views.py` | The session page, task and subagent views, one view per tool |
| `web/app.py` | The WSGI app: `Request`, `Response`, routing, the review form's `Decision` |

## Search: every word, landing on its turn

`search.py`, standard library only. A query is words and `"quoted phrases"`; a
*block* (one ask, one answer, or one step of work) matches when it holds all of
them. Blocks are small on purpose: a hit always names a turn, and the link opens
that turn with the words marked (`?hl=`) and folded work opened around them.

- **Facets**: All, Asks, Answers, Work, with counts, so a query that mostly
  hits tool output can be narrowed to what was said.
- **Conversation first**: in each session, asks then answers come before work,
  which matches far more often and matters less. Sessions are newest first.
- **What isn't searched**: file contents the assistant only *read* (Read,
  WebFetch results). Searching them finds every file, not the conversation.
  Commands, edits and command output are searched.
- Measured on real data (17 sessions): well under the 1 s trigger for an
  index, so there is none.

## The brief: where a project stands

`brief.py`, from the record only. The page to open when you come back
(`/p/<project>`, linked from the rail and every session's kicker), and the same
thing as Markdown with source links (`/p/<project>.md`, `matters brief`):

- **Where you left off**: the latest session's last ask and answer, and the
  resume command.
- **Still open**: each session that ended unfinished, and how: the assistant's
  closing line was a question to you; the last check (tests, lint, types) was
  still failing; your last ask got no answer; you interrupted the work. These
  are the same checks that put a ring next to the session in the rail.
- **Settled**: accepted knowledge scoped to the project.
- **Files touched**: every file inside the project, most recently changed
  first, with the turns that changed it (failed edits changed nothing and don't
  count). Files edited outside the project are counted, not listed.
- **Sessions**: all of them, with how each ended.

`tests/test_acceptance.py` holds the brief of the fixture project line for line.

## A file's stack: what happened to one file

`changes.py`, from the record only. Every change the assistant made to a file is
one layer: the turn that made it, what you had asked there, and the diff it
recorded. An Edit records the snippet it replaced, not the whole file, so the
layers can't be folded into one net diff; a stack is the honest shape. Failed
edits changed nothing: they are counted, not stacked. Nothing is read from disk
or git, which would show the file as it is now rather than as the session left it.

`/f?path=…&s=<session>` is one session's stack, latest on top (`order=oldest`
flips it); without `s` it spans every session, divided by session. Clicking a
file in a session's index or a turn's margin line opens the same stack in a
drawer over the reading, the edited files as a tree on its left (`panel=1` returns the fragment), scrolled to the layer
that turn added; `j`/`k` step through layers, `e` folds them, Escape closes.
Each layer is numbered by its turn.
Without the page script the link is the page. The brief's files open the
all-sessions stack.

## Tasks and subagents: the work the assistant organised

`tasks.py` rebuilds the assistant's checklist by replaying TaskCreate and
TaskUpdate (or TodoWrite, which rewrites the whole list) in order: each task,
where it ended, and the turns that moved it. Nothing is stored; it is read from
the calls, like everything else.

A subagent is an `AgentRun` on the session (`session.agents`): the call that
started it, its own journal (a separate file, never mixed into the session's
entries), its model, and how it ended, figures included. The Claude adapter
fills it; nothing outside the adapter knows the file layout or the
notification tags. A run is a card in the turn that started it and opens in the
same drawer as a file's stack (`/s/<session>/agents/<id>`, `panel=1` for the
fragment), with the session's subagents on its left.

**Still running.** Pages are snapshots, and say when what they show is still
moving. A session is live while something was recorded in it (its own journal
or a subagent's) in the last five minutes (`Session.is_live(now)`); a run
nothing says ended is running while its journal is that fresh, and "stopped
without a result" once it went quiet. The times are the journals' own, not file
times, so a page drawn for a given moment always comes out the same. Live
things pulse (the rail, the "Running" line, the run's state, the task in
progress), and a Refresh link reloads the page or, in the drawer, just the run,
where you were in it. No polling: if refreshing by hand proves tedious, polling
can use the same test.

## Model calls

Only knowledge extraction calls a model. **What the model reads**
(`transcript.py`): the selected sessions, oldest first, as `<session id="S1">` /
`<turn n="5">` blocks. The human's words are kept in full; pasted text, tool work
(one line per call) and the assistant's answers are shortened, in that order,
until the selection fits the budget (`MATTERS_MAP_BUDGET`, 600k characters).
Thinking and system reminders are left out; secrets are redacted first
(`redact.py`). **The request** goes through the Provider role, which runs the
local Claude Code CLI headless on the user's own sign-in: `claude -p
--no-session-persistence --restricted --tools ""`, our system prompt, the schema
as `--json-schema`, the transcript on stdin, `MATTERS_MODEL` / `MATTERS_EFFORT`
passed through. No session file is written, so a run never shows up among the
sessions; restricted mode skips the user's hooks and settings. Runs start in
one folder of matters' own state directory. **It runs in the background**
(`jobs.py`): the job page polls until it is done; the server is threaded so
other pages stay quick. **Safety**: POSTs from other origins and requests with
a non-local `Host` are refused (a model call uses the user's plan).

## Session timeline: how the time went

At the top of every session page, folded under its one-line summary (active
time, you vs assistant, checks, tokens) so the conversation stays first. Open,
one lane per activity on one axis of *active* time (gaps over 10 min for a step
or 15 min between turns count as away, marked on the axis). It remembers
whether you left it open.

- **Activity** (`timeline.py`, from the record, free and exact): you, discuss,
  explore, build, verify, debug, run. A step owns the time since the previous
  event (a record is written when its step is done) plus its tool's running
  time. Shell commands are classified by what they run (pytest/ruff/curl to
  localhost → verify, `sed -i`/heredoc writes/installs → build, serve/git →
  run, the rest → explore). The assistant's words take the activity of the
  tool they lead to; only a turn's closing words are discussion. Work between
  a failed check and the next passing one is debug. Summary: active time, you
  vs assistant, checks and failures, build → verify rounds that ended green.

One lane per category means ink blocks need no colour; failed checks are the
one exception (`--err`). Every block links to its turn.

**Token use** comes from the record too: each model call's usage
(`Entry.tokens`, on the call's first step; Claude Code repeats a call's usage
on every record it splits the call into, so it is counted once). Hover cards
on blocks show tokens in, out and cached; three-bar meters on lane totals and
in the turn index say high / medium / low, relative to the session (over twice
the average is high, under half is low), compared by cost-weighted tokens
(output ×5, cache writes ×1.25, cache reads ×0.1 of fresh input).

Model-made labels per turn (requirements, architecture, design…) were cut in
iteration 11: they cost a call per session and nobody acted on them. The
activity lanes, from the record, stayed.

`Workbench` (`workbench.py`) holds what needs a model: the provider, the
extractor, the knowledge store and the background `Jobs`.

## Diagrams

**Mermaid is drawn** in answers, by a pinned copy bundled with matters
(`web/vendor/`, checksum tested) and served from this viewer: the policy allows
scripts from `'self'` and nowhere else. It loads only on pages with a diagram,
runs in strict mode (no scripts or click handlers in diagrams), takes its
colours from the palette, and a diagram that does not parse stays source with a
note.

## Knowledge: preferences and facts, vetted

The goal is tacit knowledge made explicit: how you want things done
(**preferences**) and what is true about your projects (**facts**), written so a
future assistant can read it. It shows mostly in how you react to an assistant,
so extraction is built around that.

- **Extract on demand, in two calls.** Pick sessions (each shows whether it
  was read before; a live estimate of tokens).
  1. *Read.* A model reads the transcript (including your answers to the
     assistant's multiple-choice questions) plus everything you already
     accepted (with ids) and rejected. It writes one entry per turn: what the
     turn reveals (a preference, a decision, a fact, or nothing lasting) and,
     if anything, a proposal. Walking every turn is what a light model does
     reliably; asked for a list of findings, it lost most of them.
  2. *Edit.* A second, smaller call sees only the candidates and your own
     words, turn by turn. It applies one test: would an assistant that has
     already read the code still act differently for being told this? Feature
     requests restated are dropped (the code shows them), what remains is
     rewritten to the durable rule, repeats are merged, and how you work with
     an assistant, often a pattern across turns, is added where the first pass
     missed it. If the edit fails, the first pass's list stands.
  Nothing is inferred from silence, no reason is supplied that you did not
  give, and secrets are redacted before either call.
- **What you already wrote is known.** `CLAUDE.md`, `AGENTS.md`,
  `PREFERENCES.md` and `FACTS.md` (in `~/.claude/`, each picked project and its
  `.claude/`) go into the first call as `<already_written>`; the prompt says
  never to propose them again. Read only, redacted, capped.
- **Every item is traceable, both ways.** Each cites the session, the turn
  and a short verbatim quote of *your* words, shown on its row; a proposal
  without valid evidence is dropped. Each says whether you stated it or it
  follows from a reaction. The cited turn shows the item back, and a project's
  brief lists what was accepted for it.
- **Vet as a list.** Review, Accepted, Rejected. Tick rows or whole groups and
  accept or reject them together, or decide one row with its own buttons.
  Statements are edited in place; scope switches between global and the
  project. A proposal that updates or contradicts an accepted item shows that
  item, and accepting it retires the old one. What the last extraction brought
  is marked: its new items say "New" and lead their groups, and known items it
  added evidence to say "More evidence". The marks are item ids in the URL
  (`new=`, `merged=`), carried across decisions, so they last until you leave
  the list.
- **Nothing comes back twice.** A repeat of a known item (same words, or the
  model marking it a duplicate) adds its evidence to that item instead; a repeat
  of a rejected item is dropped.
- **Export on demand.** Accepted items for one scope become `PREFERENCES.md` and
  `FACTS.md` (sections by category, the reason where you gave one), to copy or
  download. matters does not write them anywhere: where they go, and the
  `@PREFERENCES.md` / `@FACTS.md` imports in `CLAUDE.md`, stay your call.

Roles: **Extractor** (`extract(transcript, known, projects) -> Extracted`), played
by `LlmExtractor` over any Provider; the edit pass lives in `knowledge/editor.py`
and is part of that one role.

## Practices from *99 Bottles of OOP*, and where they show up

| Practice | Here |
| --- | --- |
| **Shameless Green**: the simplest code that passes, duplication allowed | The original Ruby spike: one class with no abstractions |
| **Open/closed as a trigger**: refactor only when a new requirement doesn't fit | Codex arrived → Source role; a second model provider → Provider role. Scope and Renderer were never needed and left the plan |
| **Flocking rules**: find the most alike things, change the smallest difference | Claude and Codex parsing differed only in "how a line becomes an Entry". That difference became the adapter; everything else stayed shared |
| **Name the concept one level up** | Not `ClaudeMessage` but `Entry`; not `UserPrompt` but `Turn.ask` |
| **Replace conditionals with polymorphism** | `ToolView` subclasses instead of `if name == "Bash"` chains; the generic view is the default, so unknown tools still render. No `if provider` anywhere; `all_sources()` is one list. A self-registering registry (or `importlib.metadata` entry points for third-party adapters) returns when providers multiply |
| **Dependency injection** | `Viewer(sources, bench)`, `Workbench(provider, db, extractor=, jobs=, home=)`; adapters take `root=` so tests use fixtures |
| **Role tests for fakes** | `FakeSource`, `FakeProvider` and `FakeExtractor` pass the same Protocol checks as the real players |
| **Tests at the stable boundary** | One acceptance test has protected every iteration ("map this project" until iteration 10, "brief this project" since); unit tests sit under it |
| **Delete what isn't used** | Iteration 11 cut four features whose use was counted (maps, artifacts, topics, focus labels), and their roles with them |

## Deferred decisions and their triggers

| Decision | Deferred until |
| --- | --- |
| ~~Secret redaction~~ | Built in iteration 8, before anything reaches a model |
| ~~Search over answers and tool output~~ | Built in iteration 11, without an index |
| ~~Syntax highlighting in code blocks~~ | Built in iteration 11, in ink |
| File watcher + incremental byte offsets | Someone wants a page to update while a session runs |
| SQLite + FTS5 for sessions | A scan or a search takes over ~1 s |
| Writing PREFERENCES.md / FACTS.md into a project | You ask for it; until then export is copy or download |
| Live push (SSE) instead of reload | Reload-to-refresh gets in the way in daily use |
| A second Source (Codex, Cursor…) | You run another agent you want to read here |
| Model-made summaries (of a session, of a project) | The brief, from the record, turns out not to be enough |

## The test that decides whether to keep building

Come back to a project after a few days away and start from its brief. If it
gets you working again faster than scrolling the last session, and search finds
what you half-remember, keep going. If you still end up opening the raw session,
find out what the brief missed before building anything else.
