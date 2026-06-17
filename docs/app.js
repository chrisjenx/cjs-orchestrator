/* =========================================================================
 * Agentic Pipeline Explainer — interactive data + behaviour
 * Self-contained, no dependencies. Open index.html directly.
 * The data below models a real /develop pipeline so other teams can see
 * the moving parts and adapt the shape to their own codebase.
 *
 * PUBLIC REPO — genericized from a real case study. Keep it stack-neutral; do
 * not reintroduce project-specific data (real agent names, commit SHAs, brand,
 * private metrics). Figures in `SCORECARD` are representative/anonymized.
 * See /CLAUDE.md → "Keep it generic".
 * ========================================================================= */

/* ---- The pipeline: every phase /develop walks, spec -> committed branch ---- */
const PHASES = [
  {
    id: 'intake', group: 'Setup', label: 'Intake', n: '1',
    runsIn: 'main loop',
    tagline: 'Turn a ticket, spec, or rough idea into source material.',
    uses: [
      { type: 'skill', name: '/develop' },
      { type: 'tool', name: 'Linear MCP' },
      { type: 'tool', name: 'git: docs branch' },
    ],
    mechanics: [],
    detail: [
      'Resolve the argument: a Linear ticket id/URL, a spec file or directory, an inline description, or a one-line idea.',
      'Pull every related artifact before planning — ticket body + relations, design docs, and any mocks attached to the ticket <em>or its parent</em>. Heavy artifacts live on an orphan <code>docs</code> branch, fetched with <code>git show</code> (no external auth a sub-agent can lose mid-run).',
      'Lesson for your own pipeline: <strong>gather context once, durably, where every sub-agent can reach it.</strong> Anything gitignored or session-scratch is invisible to a fresh sub-agent.',
    ],
  },
  {
    id: 'worktree', group: 'Setup', label: 'Worktree', n: '2',
    runsIn: 'main loop',
    tagline: 'Isolate the work on its own branch + checkout.',
    uses: [
      { type: 'tool', name: 'git worktree' },
    ],
    mechanics: ['gate'],
    detail: [
      'Create an isolated checkout so parallel runs and the human\'s working copy never collide. Hard-stop if you\'re on <code>master</code>.',
      'Rebase onto <code>origin/master</code> if the base has drifted — a stale base makes diffs surface unrelated files that poison every reviewer downstream.',
      'Lesson: <strong>every agent that runs a build must be rooted in this checkout.</strong> A sub-agent shell rooted elsewhere silently tests the wrong tree and returns a verdict for code your branch never changed.',
    ],
  },
  {
    id: 'assess', group: 'Setup', label: 'Assess', n: '3',
    runsIn: 'main loop',
    tagline: 'Compile one config object the whole run reads.',
    uses: [{ type: 'artifact', name: 'config{}' }],
    mechanics: [],
    detail: [
      'Classify the work into a single <code>config</code>: scope (small / medium / large), touched layers, risk markers, which audit agents to seed, retry caps, whether the validator can be skipped.',
      'Size by <em>new</em> work, not surface area. Eight endpoints wiring to an already-tested service is <em>small</em>; one new permission rule is not.',
      'List every blocking unknown in <code>ambiguities</code> so the next phase fires. <strong>The config is the dial-set</strong> — the same template runs every feature; you tune values, not logic.',
    ],
  },
  {
    id: 'clarify', group: 'Setup', label: 'Clarify', n: '4',
    runsIn: 'main loop',
    tagline: 'Ask the human the blocking questions — once.',
    uses: [{ type: 'tool', name: 'AskUserQuestion' }],
    mechanics: ['human'],
    detail: [
      'This is the <strong>primary human-in-the-loop seam</strong>. If the spec is thin or <code>ambiguities</code> is non-empty, ask here, then fold answers into the brief.',
      'After this, the run goes autonomous — it pauses again only when a phase exhausts its retries with an unresolved high-severity finding.',
      'Lesson: <strong>front-load human judgement.</strong> Cheap to ask before planning; expensive to discover a wrong assumption after twelve agents built on it.',
    ],
  },
  {
    id: 'plan', group: 'Plan', label: 'Plan', n: '5',
    runsIn: 'discover → judge → review (candidates only at raised intensity)',
    tagline: 'Discover reuse, then write a phase-node plan and review it.',
    uses: [
      { type: 'agent', name: 'spec-analyzer' },
      { type: 'agent', name: 'plan-explorer' },
      { type: 'agent', name: 'plan-reviewer' },
      { type: 'skill', name: '/plan-work' },
    ],
    mechanics: ['fork', 'gate'],
    detail: [
      'A tiered discovery runs first: a mechanical pass inventories the codebase, four cheap parallel finders return evidence (what to reuse, the closest reference feature, scope, open questions).',
      '<span class="hl-fork">Forking:</span> when intensity is raised, the planner <strong>forks into N candidates</strong> — reuse-first, risk-first, simplicity-first — all consuming the same facts, and a synthesizer picks the best. Diverge, then converge.',
      'The output is a plan file with <code>### PN</code> phase nodes, machine-checkable gate tokens, and a manifest. An independent <code>plan-reviewer</code> (fresh context, no prior conversation) must PASS it.',
      '<span class="hl-gate">Hard gate:</span> no phase nodes + no logged PASS → the run terminates as <code>planning-failed</code>. No code is written against a plan that didn\'t pass review.',
    ],
  },
  {
    id: 'domain', group: 'Build', label: 'Domain phases  P1…PN', n: '6',
    runsIn: 'one nesting executor per phase',
    tagline: 'One executor per cohesive phase, writing prod + tests together.',
    uses: [
      { type: 'agent', name: 'executor (general-purpose)' },
      { type: 'agent', name: 'backend-scaffolder' },
      { type: 'agent', name: 'ui-codegen' },
      { type: 'agent', name: 'ui-evaluator' },
      { type: 'agent', name: 'backend-test-writer' },
    ],
    mechanics: ['nest', 'gate'],
    detail: [
      'The orchestrator walks the plan: find the first phase whose dependencies are all <code>DONE</code>, flip it <code>IN_PROGRESS</code>, dispatch <strong>one</strong> executor with that phase\'s nodes inlined verbatim.',
      '<span class="hl-nest">Nesting:</span> the executor exists <em>because it can spawn its own children</em>. It runs writer→evaluator GAN loops, scaffolders, and test-writers — depth the flat orchestrator can\'t reach. The orchestrator only ever holds phase status; the heavy reading lives inside each executor.',
      'A phase is cohesive: a service + its controller + DTO + tests = <em>one</em> phase, not four. Prod and tests are written together so the coverage gate is satisfied on the first pass.',
      '<span class="hl-gate">Cheap gates run here</span> (single-module compile, one named test, scoped lint). Heavy gates are tagged <code>DEFERRED-PF</code> and run later. On return the orchestrator <strong>re-reads the plan file</strong> to confirm the phase reached DONE — it never trusts the reply.',
    ],
  },
  {
    id: 'pv', group: 'Quality tail', label: 'PV — Validate', n: '7',
    runsIn: 'one validator',
    tagline: 'Does the diff actually satisfy every requirement?',
    uses: [{ type: 'agent', name: 'feature-validator' }],
    mechanics: ['gate'],
    detail: [
      'Diff the branch against the requirements table. PASS → advance. ITERATE → convert each gap into a fix-in-place subtask and re-walk, bounded by a retry cap.',
      'Discipline that matters: <strong>a red or flaky test is a gap (fix it), never a missing capability (replan it).</strong> Re-planning already-built work churns forever and can\'t fix a race.',
    ],
  },
  {
    id: 'pa', group: 'Quality tail', label: 'PA — Audit', n: '8',
    runsIn: 'starts with completeness; climbs a defect-gated ladder',
    tagline: 'Independent reviewers hunt for what\'s missing or wrong.',
    uses: [
      { type: 'agent', name: 'audit-completeness-checker' },
      { type: 'agent', name: 'audit-stubs-scanner' },
      { type: 'agent', name: 'audit-edge-case-reviewer' },
      { type: 'agent', name: 'audit-regression-checker' },
      { type: 'agent', name: 'audit-fresh-eyes-reviewer' },
    ],
    mechanics: ['fork', 'gate'],
    detail: [
      '<span class="hl-fork">Forking:</span> each round\'s seeded set runs as a <strong>parallel fan-out</strong> of flat, independent leaves — but the set <em>starts at one</em> (completeness) and grows reactively. Findings dedupe by fingerprint against a registry.',
      'A <em>reactive ladder</em>: start with the broadest lens (completeness) and add the next rung only after a round actually finds a defect. Cheap when the code is clean, deep when it isn\'t.',
      '<span class="hl-gate">Gate:</span> defects spawn fix subtasks and re-walk; a clean round advances. Bounded by a round cap so it always terminates.',
    ],
  },
  {
    id: 'pt', group: 'Quality tail', label: 'PT — Tidy', n: '9',
    runsIn: 'forked reviewer fan-out',
    tagline: 'Convention + quality reviewers, fix-in-place.',
    uses: [
      { type: 'skill', name: '/tidy' },
      { type: 'agent', name: 'backend-pattern-reviewer' },
      { type: 'agent', name: 'ui-reviewer' },
      { type: 'agent', name: 'api-contract-reviewer' },
    ],
    mechanics: ['fork', 'gate'],
    detail: [
      'Run the changed-module lint gate first, then <span class="hl-fork">fork a path-routed reviewer set</span> — self-scaled to the size of the change. Touch the API layer and the contract reviewer is always included.',
      'Fixes land in place. Anything that needs a human decision is surfaced at a between-phase gate before finalize.',
    ],
  },
  {
    id: 'pf', group: 'Quality tail', label: 'PF — Finalize', n: '10',
    runsIn: 'nesting runners',
    tagline: 'Run every heavy gate for real. Commit. No push.',
    uses: [
      { type: 'agent', name: 'gate runners' },
      { type: 'artifact', name: 'report.md' },
      { type: 'artifact', name: 'Green SHA' },
    ],
    mechanics: ['nest', 'gate'],
    detail: [
      'Every gate deferred during the build runs now, locally, blocking until green: whole-module build, full suite, multi-target check, diff-coverage, lint.',
      '<span class="hl-gate">Coverage is a real gate</span> — an empty or all-skipped report is never a pass. A genuinely red gate gets one fix attempt, then the run commits with a failure flag rather than looping forever.',
      'Write the report + a per-run retro, commit a Green SHA — <strong>but never push.</strong> The run hands off.',
    ],
  },
  {
    id: 'relay', group: 'Handoff', label: 'Relay', n: '11',
    runsIn: 'main loop',
    tagline: 'Derive terminal status. Hand off to the push loop.',
    uses: [{ type: 'skill', name: '/commit-push-watch' }],
    mechanics: ['human'],
    detail: [
      'Derive the terminal status mechanically from the gate record — <code>ready</code>, <code>ready-with-escalations</code>, <code>committed-with-failures</code>, <code>commit-failed</code>, or <code>planning-failed</code> — never from optimistic prose.',
      'Push only on a clean / escalations status, and only via the push-and-watch loop that babysits CI and review threads until green.',
      'Lesson: <strong>the boundary between "built" and "shipped" is a deliberate human checkpoint.</strong>',
    ],
  },
];

const GROUP_ORDER = ['Setup', 'Plan', 'Build', 'Quality tail', 'Handoff'];

/* ---- Forking vs Nesting: the two-axis model ---- */
const MECH = {
  nest: {
    title: 'Nesting',
    sub: 'depth — an agent that dispatches its own agents',
    color: 'var(--nest)',
    points: [
      'The orchestrator dispatches <strong>one executor per phase</strong>. That executor spawns its <em>own</em> children — writers, a writer→evaluator loop, test-writers, scaffolders.',
      'It exists to add a layer of delegation. Flat workflow leaves can\'t nest; a dispatched executor can — so the depth lives there.',
      'The win: the orchestrator\'s context stays tiny (phase status only). Each executor carries the heavy reading for <em>its</em> slice and nothing else. Context never fills.',
    ],
    when: 'When a unit of work needs sub-steps that each deserve clean context — and you want the parent to stay a thin coordinator.',
  },
  fork: {
    title: 'Forking',
    sub: 'breadth — N copies from one starting point, then converge',
    color: 'var(--fork)',
    points: [
      'Spawn <strong>several agents from one context</strong>, run them independently, then judge or synthesize a single answer.',
      'Discovery <em>always</em> fans out four finders. Tidy forks a path-routed reviewer set. Audit <em>starts at one</em> and climbs a defect-gated ladder. The planner forks reuse-/risk-/simplicity-first candidates — and adversarial checks fork N skeptics — only <em>when intensity is raised</em> (lean default: one of each).',
      'The win: independent reads catch what one pass misses, and parallel work collapses wall-clock. The convergence step — a judge, a synthesizer, a vote — turns divergence into a decision.',
    ],
    when: 'When the solution space is wide or a claim needs verifying — diverge, then select. One attempt iterated loses to N attempts judged.',
  },
};

/* ---- Portable moves: principles you can lift — several mapping to Anthropic's named patterns ---- */
const PATTERNS = [
  {
    name: 'State lives in a file',
    body: 'One markdown file is the system of record — phase nodes with statuses, an append-only log, a findings registry. Orchestrator and every agent read and write it by heading. No engine to host: a crash resumes by re-reading — skip DONE, re-enter the first IN_PROGRESS.',
    takeaway: 'Make state a durable artifact, not in-memory context. Crash-resume comes free.',
  },
  {
    name: 'Narrow the context', ref: 'Orchestrator-workers',
    body: 'Hand each agent its slice <em>verbatim</em> — the phase\'s nodes, the worktree root, a hard scope fence, nothing else. The orchestrator holds only phase status; each executor carries the heavy reading for its job alone and never sees the rest of the plan.',
    takeaway: 'Narrow context, fewer stray edits — and the coordinator never fills up.',
  },
  {
    name: 'Route to specialists', ref: 'Routing',
    body: 'A registry of tightly-scoped writers, scaffolders, reviewers, auditors. A routing table maps an artifact <em>shape</em> — UI file, client-API stamp, migration — to the right one; glue work falls back to a generalist.',
    takeaway: 'Specialists beat one generalist — when the registry routes by artifact shape, not reflex.',
  },
  {
    name: 'Tier the models', ref: 'Evaluator-optimizer',
    body: 'Cheap models for mechanical work (lint, grep, commits), mid for code + tests, top tier only for hard judgement (plan, validate, UI). And pit them: the agent that <em>evaluates</em> a UI runs a different tier than the one that <em>wrote</em> it.',
    takeaway: 'Match model cost to the call; adversarial pairing catches what self-review won\'t.',
  },
  {
    name: 'Verify by forking', ref: 'Parallelization · voting',
    body: 'Per claim, fork N skeptics each told to <em>refute</em> it — kill it on a majority. For open questions, run N attempts from different angles and judge the winner. One pass iterated loses to N judged.',
    takeaway: 'Diverge, then select — plausible-but-wrong dies in the panel.',
  },
  {
    name: 'Gates that can\'t be skipped', ref: 'Prompt chaining',
    body: 'Each control is a machine-checkable token — <code>test:&lt;Class&gt;</code>, <code>cov&gt;=60</code>, <code>build:&lt;module&gt;</code> — that clears only when a command produced <em>evidence</em>, not when an agent felt done. The orchestrator appends them (the planner can\'t), so they never fall off the end and they block the commit until they clear.',
    takeaway: 'Encode "done" as commands with evidence, bolted on structurally — judgement-based controls get skipped under pressure.',
  },
  {
    name: 'Close the loop', ref: 'Autonomous agents',
    body: 'Classify every residual finding <em>preventable</em> (a plan check could\'ve required it) or <em>irreducible</em>. Each preventable one books a plan-time anchor the planner satisfies next run — the flywheel above, made mechanical.',
    takeaway: 'Feed reviewer findings back into the planner. The line tightens every run.',
  },
];

/* ---- Residual-feedback flywheel (animated) ---- */
const FLY_STAGES = [
  { a: -90, label: 'Run', sub: 'the walk completes' },
  { a: -18, label: 'Residual findings', sub: 'audit + tidy log them' },
  { a: 54, label: 'Preventable?', sub: 'vs the irreducible floor' },
  { a: 126, label: 'New plan anchor', sub: 'grep / token / lint' },
  { a: 198, label: 'Stronger planner', sub: 'satisfies it next run' },
];
const FLY_INIT = 8;
const FLY_FLOOR = 2;
// Plan-time anchors promoted from residual findings (representative examples).
const FLY_RUNS = [
  { anchor: 'A1', note: 'enum field defaults to UNKNOWN', prev: 7 },
  { anchor: 'A2', note: 'new DTO ⇒ a serialization test', prev: 6 },
  { anchor: 'A3', note: 'enumerate every DTO call-site', prev: 4 },
  { anchor: 'A4', note: 'in-tx publish is never swallowed', prev: 3 },
  { anchor: 'A5', note: 'await afterCommit, no fixed delay', prev: 2 },
  { anchor: 'A6', note: 'wire-snapshot parity guards', prev: 1 },
  { anchor: 'grep', note: 'each recurring class → a mechanical anchor', prev: 0 },
];
const FLY_SVG = `<svg class="fly-svg" viewBox="0 0 400 400" aria-hidden="true">
  <defs>
    <linearGradient id="flyGrad" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#a371f7"/><stop offset=".5" stop-color="#2dd4bf"/><stop offset="1" stop-color="#f0a020"/>
    </linearGradient>
    <path id="fly-ring-path" d="M200,64 A136,136 0 1,1 200,336 A136,136 0 1,1 200,64"/>
  </defs>
  <circle class="fly-ring-dash" cx="200" cy="200" r="136"/>
  <circle class="fly-ring" cx="200" cy="200" r="136"/>
  <circle class="fly-hub-ring" cx="200" cy="200" r="62"/>
  <circle class="fly-dot" r="9"><animateMotion dur="6s" repeatCount="indefinite" rotate="auto"><mpath href="#fly-ring-path"/></animateMotion></circle>
</svg>`;

let flyI = 0, flyHold = 0, flyTimer = null;

function renderFlywheel() {
  const wheel = document.querySelector('#fly-wheel');
  const live = document.querySelector('#fly-live');
  if (!wheel || !live) return;
  const chips = FLY_STAGES.map((s, i) => {
    const r = s.a * Math.PI / 180, x = 50 + 37 * Math.cos(r), y = 50 + 37 * Math.sin(r);
    return `<div class="fly-stage" style="left:${x.toFixed(1)}%;top:${y.toFixed(1)}%"><span class="fly-stage-n">${i + 1}</span><span class="fly-stage-l">${s.label}</span><span class="fly-stage-s">${s.sub}</span></div>`;
  }).join('');
  wheel.innerHTML = FLY_SVG + `<div class="fly-hub"><span class="fly-hub-run" id="fly-run">ready</span><span class="fly-hub-cap">self-tightening</span></div>` + chips;
  live.innerHTML = `
    <span class="fly-live-label">live · the loop in action</span>
    <div class="fly-metric">
      <div class="fly-bar-row"><span>preventable escapes</span><span class="n fly-prev-n" id="fly-prev">${FLY_INIT}</span></div>
      <div class="fly-bar"><span class="fly-bar-fill fly-prev-fill" id="fly-prevfill" style="width:100%"></span></div>
      <div class="fly-bar-row"><span>irreducible floor</span><span class="n fly-floor-n">${FLY_FLOOR}</span></div>
      <div class="fly-bar"><span class="fly-bar-fill fly-floor-fill" style="width:${(FLY_FLOOR / FLY_INIT * 100).toFixed(0)}%"></span></div>
    </div>
    <div class="fly-anchors" id="fly-anchors"></div>
    <div class="fly-caption" id="fly-caption">A run finishes — the audit + tidy tail logs what slipped through.</div>`;
}

function flyTick() {
  const run = document.querySelector('#fly-run'), prev = document.querySelector('#fly-prev'),
    fill = document.querySelector('#fly-prevfill'), anchors = document.querySelector('#fly-anchors'),
    cap = document.querySelector('#fly-caption');
  if (!run) return;
  if (flyI < FLY_RUNS.length) {
    const r = FLY_RUNS[flyI];
    run.textContent = `Run ${flyI + 1}`;
    prev.textContent = r.prev;
    fill.style.width = `${r.prev / FLY_INIT * 100}%`;
    const chip = el('span', 'fly-anchor', r.anchor); chip.title = r.note; anchors.appendChild(chip);
    cap.innerHTML = `Run ${flyI + 1}: a residual finding → add <b>${r.anchor}</b> — ${r.note}. Preventable escapes now <b>${r.prev}</b>.`;
    flyI++;
  } else {
    flyHold++;
    if (flyHold === 1) { run.textContent = 'converged'; cap.innerHTML = 'Converged — preventable escapes at <b>0</b>; audit/tidy sit at the <b>irreducible floor</b>. A brand-new class still earns a brand-new anchor.'; }
    if (flyHold >= 3) { flyI = 0; flyHold = 0; anchors.innerHTML = ''; prev.textContent = FLY_INIT; fill.style.width = '100%'; run.textContent = 'Run 1'; cap.innerHTML = 'A run finishes — the audit + tidy tail logs what slipped through.'; }
  }
}
function startFlywheel() { if (!flyTimer && document.querySelector('#fly-run')) { flyTick(); flyTimer = setInterval(flyTick, 2600); } }

/* ---- Method scorecard (vanilla + 3 /develop iterations + current) ---- */
/* Cells state the actual MECHANISM each method uses on a dimension. The level
   (1–4) is a DIRECTIONAL strength reasoned from architecture + the agent-
   count anchors below — NOT a measured benchmark. */
/* Accuracy + Quality = directional (reasoned from architecture — no ground-truth
   scores exist). Wall-clock, Token spend, and agent counts = representative
   estimates from a real project's runs (anonymized). */
const SC_DIMS = [
  { name: 'Accuracy', kind: 'reasoned' },
  { name: 'Wall-clock (rel.)', kind: 'measured' },
  { name: 'Tokens / run', kind: 'measured' },
  { name: 'Quality', kind: 'reasoned' },
];
const SCORECARD = [
  {
    name: 'Vanilla', tag: 'no skill · hand-built', commit: null,
    agents: { val: '3–43', note: '25 sampled' },
    acc: { lvl: 1, txt: 'unverified — one pass, no check' },
    wall: { val: '~1.7×', note: 'rel · session-life *' },
    tok: { val: '~125M', note: 'effective/run · cache-weighted' },
    qual: { lvl: 1, txt: 'no reviewer; convention drift' },
    why: 'The heaviest effective spend (~125M cache-weighted tokens/run) — one long main-thread context re-reads the whole cache every step — and it’s unverified. Worst of both.',
  },
  {
    name: 'Skill Only', tag: 'ad-hoc /develop · gen 1', commit: null,
    agents: { val: '2–53', note: '27 sampled' },
    acc: { lvl: 2, txt: 'phases, but controls are judgement calls' },
    wall: { val: '~1.0×', note: 'rel · leanest · session-life *' },
    tok: { val: '~75M', note: 'effective/run · cache-weighted' },
    qual: { lvl: 2, txt: 'ad-hoc reviews' },
    why: 'Lightest effective spend (~75M/run) but the widest spread by far — from near-zero on a trivial run to a runaway many times the median. No durable state or gates.',
  },
  {
    name: 'Dynamic Workflow', tag: 'develop.js Workflow · gen 2', commit: null,
    agents: { val: '29–145', note: '18 sampled' },
    acc: { lvl: 3, txt: 'bounded loops + refuters + TDD' },
    wall: { val: '~1.2×', note: 'rel · session-life *' },
    tok: { val: '~120M', note: 'effective/run · cache-weighted' },
    qual: { lvl: 3, txt: 'GAN UI loop + audit' },
    why: 'Effective spend in line with the rest (~120M/run), but the worst tail — a single run hit ~310M effective (~1.7B raw). Flat workflow leaves can’t nest, and in-memory state can’t crash-resume.',
    more: 'fanout',
  },
  {
    name: 'Mechanical SubDriven Skill', tag: 'plan-walking orchestrator · current', commit: null, current: true,
    agents: { val: '13–66', note: '11 sampled' },
    acc: { lvl: 4, txt: 'planner-PASS gate + validator + adversarial audit' },
    wall: { val: '~1.7×', note: 'rel · most thorough · session-life *' },
    tok: { val: '~110M', note: 'effective/run · cache-weighted' },
    qual: { lvl: 4, txt: 'path-routed reviewers + flywheel anchors' },
    why: 'Leanest of the heavyweight methods (~110M/run) with the tightest spread — plus the planner gate, nesting, and flywheel a flat workflow can’t do. It runs longest because it checks the most; spend is comparable, the win is reliability.',
  },
];

function renderScorecard() {
  const grid = document.querySelector('#sc-grid');
  if (!grid) return;
  const meter = (lvl) => `<span class="sc-meter">${[1, 2, 3, 4].map((i) => `<i class="${i <= lvl ? 'on l' + lvl : ''}"></i>`).join('')}</span>`;
  const reasoned = (c) => `${meter(c.lvl)}<span class="sc-txt">${c.txt}</span>`;
  const measured = (c) => c.none
    ? `<span class="sc-norec">${c.txt || 'no records'}</span>`
    : `<span class="sc-meas">${c.val}</span><span class="sc-meas-note">${c.note}</span>`;
  let html = `<div class="sc-cell sc-h sc-h-method">Method</div>` +
    SC_DIMS.map((d) => `<div class="sc-cell sc-h">${d.name}<span class="sc-${d.kind === 'measured' ? 'est' : 'reas'}">${d.kind === 'measured' ? 'measured · est' : 'reasoned'}</span></div>`).join('') +
    `<div class="sc-cell sc-h">Why we moved on</div>`;
  SCORECARD.forEach((m) => {
    const cur = m.current ? ' sc-current' : '';
    const ag = m.agents ? `<span class="sc-agents">${m.agents.val} agents · ${m.agents.note}</span>` : `<span class="sc-norec">no session records</span>`;
    html += `<div class="sc-cell sc-method${cur}"><span class="sc-mname">${m.name}</span><span class="sc-mtag">${m.tag}</span>${m.commit ? `<span class="sc-mcommit">${m.commit}</span>` : '<span class="sc-mcommit sc-mcommit-none">—</span>'}${ag}</div>`;
    html += `<div class="sc-cell sc-data${cur}">${reasoned(m.acc)}</div>`;
    html += `<div class="sc-cell sc-data sc-measured${cur}">${measured(m.wall)}</div>`;
    html += `<div class="sc-cell sc-data sc-measured${cur}">${measured(m.tok)}</div>`;
    html += `<div class="sc-cell sc-data${cur}">${reasoned(m.qual)}</div>`;
    html += `<div class="sc-cell sc-why${cur}">${m.why}${m.more ? ` <button class="sc-why-more" data-insight="${m.more}">why the fan-out runs hot →</button>` : ''}</div>`;
  });
  grid.innerHTML = html;
}

/* ---- Problem: a laborious, looping manual grind (deliberately janky) ---- */
const GRIND_STEPS = ['plan', 'code', 'review', 'fix', 'push', 'CI'];
const GRIND_SAY = ['scoping by hand…', 'hand-writing it…', 'did I miss anything?…', 'patching…', 'pushing…'];
function renderManualGrind() {
  const wrap = document.querySelector('#grind'); if (!wrap) return;
  wrap.innerHTML =
    `<div class="grind-track">${GRIND_STEPS.map((s, i) => `<span class="grind-step">${s}</span>${i < GRIND_STEPS.length - 1 ? '<span class="grind-arrow">→</span>' : ''}`).join('')}</div>
     <div class="grind-meta">attempt <b id="grind-att">1</b> · <span id="grind-status" class="grind-status">grinding…</span></div>`;
  const steps = [...wrap.querySelectorAll('.grind-step')];
  const status = wrap.querySelector('#grind-status'), att = wrap.querySelector('#grind-att');
  let i = 0, n = 1;
  setInterval(() => {
    steps.forEach((s) => s.classList.remove('on', 'fail'));
    steps[i].classList.add('on');
    if (i === GRIND_STEPS.length - 1) {            // CI → always rejected, loop back to fix
      steps[i].classList.add('fail');
      status.textContent = '✗ CI rejected — back to fix'; status.classList.add('bad');
      att.textContent = ++n;
      i = 3;
    } else {
      status.textContent = GRIND_SAY[i]; status.classList.remove('bad');
      i++;
    }
  }, 950);
}

/* ---- Solution: a smooth, glowing, automatic pipeline that settles ---- */
const MAGIC_STEPS = ['intake', 'plan', 'build', 'audit', 'tidy', 'commit'];
const MAGIC_SAY = ['intake…', 'planning…', 'building…', 'auditing…', 'tidying…'];
function renderMagicPipeline() {
  const wrap = document.querySelector('#magic'); if (!wrap) return;
  wrap.innerHTML =
    `<div class="magic-track">${MAGIC_STEPS.map((s) => `<span class="magic-step"><span class="magic-orb"></span><span class="magic-lbl">${s}</span></span>`).join('')}</div>
     <div class="magic-meta"><span id="magic-status" class="magic-status">ready</span></div>`;
  const steps = [...wrap.querySelectorAll('.magic-step')];
  const status = wrap.querySelector('#magic-status');
  let i = 0, settling = false;
  setInterval(() => {
    if (settling) { settling = false; steps.forEach((s) => s.classList.remove('on', 'done')); i = 0; }
    steps.forEach((s, k) => { s.classList.toggle('on', k === i); if (k < i) s.classList.add('done'); });
    if (i === MAGIC_STEPS.length - 1) {
      status.innerHTML = '✓ settled — clean, audited, booked ✨'; status.classList.add('settled');
      wrap.classList.add('sparkle'); setTimeout(() => wrap.classList.remove('sparkle'), 900);
      settling = true;
    } else {
      status.textContent = MAGIC_SAY[i]; status.classList.remove('settled');
      i++;
    }
  }, 820);
}

/* =========================================================================
 *  Rendering
 * ========================================================================= */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
};

const USE_KIND = {
  skill: { label: 'skill', cls: 'chip-skill' },
  agent: { label: 'agent', cls: 'chip-agent' },
  tool: { label: 'tool', cls: 'chip-tool' },
  artifact: { label: 'artifact', cls: 'chip-artifact' },
};

function renderPipeline() {
  const rail = $('#phase-rail');
  PHASES.forEach((p, i) => {
    const node = el('button', 'phase-node');
    node.dataset.id = p.id;
    node.setAttribute('aria-label', `Phase ${p.n}: ${p.label}`);
    const mechDots = p.mechanics.map((m) => `<span class="mech-dot mech-${m}" title="${m}"></span>`).join('');
    node.innerHTML = `
      <span class="phase-num">${p.n}</span>
      <span class="phase-body">
        <span class="phase-label">${p.label}</span>
        <span class="phase-tagline">${p.tagline}</span>
      </span>
      <span class="phase-mech">${mechDots}</span>`;
    node.addEventListener('click', () => selectPhase(p.id));
    rail.appendChild(node);
    if (i < PHASES.length - 1) rail.appendChild(el('div', 'phase-connector'));
  });
  selectPhase(PHASES[0].id);
}

function selectPhase(id) {
  const p = PHASES.find((x) => x.id === id);
  $$('.phase-node').forEach((n) => n.classList.toggle('active', n.dataset.id === id));
  const panel = $('#phase-detail');
  const chips = p.uses.map((u) => {
    const k = USE_KIND[u.type];
    return `<button class="use-chip ${k.cls} clickable" data-cat="${u.name}"><span class="use-kind">${k.label}</span>${u.name}<span class="chip-go">↗</span></button>`;
  }).join('');
  const mechBadges = p.mechanics.map((m) => {
    const labels = { fork: 'forks', nest: 'nests', gate: 'gated', human: 'human seam' };
    return `<span class="mech-badge mech-${m}">${labels[m]}</span>`;
  }).join('');
  panel.innerHTML = `
    <div class="detail-head">
      <div class="detail-eyebrow">${p.group} · runs in: <strong>${p.runsIn}</strong></div>
      <h3>${p.n}. ${p.label}</h3>
      <div class="detail-mech">${mechBadges}</div>
    </div>
    <div class="detail-uses">${chips}</div>
    <div class="detail-prose">${p.detail.map((d) => `<p>${d}</p>`).join('')}</div>`;
  panel.classList.remove('flash');
  void panel.offsetWidth; // reflow to restart the animation
  panel.classList.add('flash');
}

function renderMechanics() {
  const wrap = $('#mech-cards');
  ['nest', 'fork'].forEach((key) => {
    const m = MECH[key];
    const card = el('div', `mech-card mech-card-${key}`);
    card.innerHTML = `
      <div class="mech-card-head">
        <span class="mech-glyph mech-glyph-${key}">${key === 'nest' ? svgNest() : svgFork()}</span>
        <div>
          <h3>${m.title}</h3>
          <p class="mech-sub">${m.sub}</p>
        </div>
      </div>
      <ul class="mech-points">${m.points.map((pt) => `<li>${pt}</li>`).join('')}</ul>
      <div class="mech-when"><span>When</span>${m.when}</div>`;
    wrap.appendChild(card);
  });
}

/* Small inline SVGs for the two mechanics */
function svgNest() {
  return `<svg viewBox="0 0 64 64" width="40" height="40" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
    <circle cx="32" cy="10" r="5"/>
    <path d="M32 15 v8"/>
    <circle cx="32" cy="30" r="5"/>
    <path d="M32 35 v6 M22 47 v-6 h20 v6 M42 47 v-6"/>
    <circle cx="22" cy="52" r="5"/><circle cx="42" cy="52" r="5"/>
  </svg>`;
}
function svgFork() {
  return `<svg viewBox="0 0 64 64" width="40" height="40" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
    <circle cx="32" cy="10" r="5"/>
    <path d="M32 15 v6 M12 33 v-6 c0-3 0-6 20-6 20 0 20 3 20 6 v6"/>
    <circle cx="12" cy="38" r="5"/><circle cx="32" cy="38" r="5"/><circle cx="52" cy="38" r="5"/>
    <path d="M12 43 v4 c0 4 0 6 20 6 20 0 20-2 20-6 v-4"/>
    <circle cx="32" cy="58" r="4"/>
  </svg>`;
}

function renderPatterns() {
  const wrap = $('#pattern-grid');
  PATTERNS.forEach((p) => {
    wrap.appendChild(el('div', 'pattern-card',
      `<div class="pat-head"><h4>${p.name}</h4>${p.ref ? `<span class="pat-ref" title="Anthropic · Building Effective Agents">≈ ${p.ref}</span>` : ''}</div>` +
      `<p>${p.body}</p>` +
      `<p class="block-takeaway"><span>Takeaway</span>${p.takeaway}</p>`));
  });
}

/* ---- Animated token travelling the pipeline spine ---- */
function animateFlow() {
  const rail = $('#phase-rail');
  const nodes = $$('.phase-node', rail);
  let i = 0;
  setInterval(() => {
    nodes.forEach((n) => n.classList.remove('pulse'));
    nodes[i % nodes.length].classList.add('pulse');
    i++;
  }, 1100);
}

/* ---- Scroll-spy for the section nav ---- */
function setupNav() {
  const links = $$('.nav-link');
  const map = new Map(links.map((l) => [l.getAttribute('href').slice(1), l]));
  const obs = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) {
        links.forEach((l) => l.classList.remove('active'));
        map.get(e.target.id)?.classList.add('active');
      }
    });
  }, { rootMargin: '-45% 0px -50% 0px' });
  $$('section[id]').forEach((s) => obs.observe(s));
}

/* ---- Legend filter: highlight phases by mechanic ---- */
function setupLegend() {
  $$('.legend-item').forEach((item) => {
    item.addEventListener('click', () => {
      const m = item.dataset.mech;
      const on = item.classList.toggle('active');
      $$('.legend-item').forEach((o) => { if (o !== item) o.classList.remove('active'); });
      $$('.phase-node').forEach((n) => {
        const id = n.dataset.id;
        const p = PHASES.find((x) => x.id === id);
        const match = !on || p.mechanics.includes(m);
        n.classList.toggle('dimmed', on && !match);
      });
    });
  });
}

document.addEventListener('DOMContentLoaded', () => {
  renderPipeline();
  renderMechanics();
  renderPatterns();
  renderFlywheel();
  renderScorecard();
  renderManualGrind();
  renderMagicPipeline();
  animateFlow();
  setupNav();
  setupLegend();
  // start the flywheel animation when its section scrolls into view
  const flySec = document.querySelector('#flywheel');
  if (flySec) {
    const o = new IntersectionObserver((entries) => {
      entries.forEach((e) => { if (e.isIntersecting) startFlywheel(); });
    }, { threshold: 0.25 });
    o.observe(flySec);
  }
  // Clicking a skill/agent/tool chip opens its catalog entry (defined in catalog.js).
  document.addEventListener('click', (e) => {
    const chip = e.target.closest('.use-chip[data-cat]');
    if (chip && window.openCatalog) window.openCatalog(chip.dataset.cat);
    const more = e.target.closest('.sc-why-more[data-insight]');
    if (more && window.openInsight) window.openInsight(more.dataset.insight);
  });
});
