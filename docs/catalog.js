/* =========================================================================
 * Catalog: clickable skills & agents + the file anatomy you'd build.
 * Grounded in the real .claude/ file shapes so the templates are copyable.
 *
 * PUBLIC REPO: the CATALOG uses generic role names. Keep them stack-neutral;
 *    don't reintroduce real internal agent/skill names. See /CLAUDE.md.
 * ========================================================================= */

/* Build-guidance archetypes for agents (tools/model reflect the real tiering). */
const ARCHETYPE = {
  planner:    { tools: 'Read, Grep, Glob, Bash (read-only)', model: 'opus, deep judgement', note: 'Read-heavy; writes only the plan, never edits source.' },
  executor:   { tools: 'All tools', model: 'sonnet, build', note: 'The one agent that NESTS: it spawns its own writers, test-writers, and evaluator loops for its phase.' },
  codegen:    { tools: 'All tools', model: 'sonnet, build (UI uses opus)', note: 'Writes production code AND its tests together, following project templates.' },
  validator:  { tools: 'All tools (mostly read + run tests)', model: 'opus, deep judgement', note: 'Diffs the build against a checklist; classifies each miss as a gap (fix) vs a missing capability (replan).' },
  evaluator:  { tools: 'All tools', model: 'sonnet, adversarial to the writer', note: 'Scores an artifact against a rubric: PASS, or FAIL with feedback the writer consumes next round.' },
  auditRO:    { tools: 'Bash, Glob, Grep, Read', model: 'opus, judgement (cheap refuters use haiku)', note: 'A flat parallel LEAF, never nests. One narrow lens over the diff; returns findings only.' },
  reviewer:   { tools: 'All tools', model: 'tier by depth (haiku to opus)', note: 'Checks changed files against one convention/quality dimension; fixes in place or flags.' },
  runner:     { tools: 'Bash', model: 'haiku, mechanical', note: 'Cheap mechanical runner: cd into the worktree, run a heavy build gate, report pass/fail.' },
};

/* The cast. Keyed by the exact chip text used in app.js PHASES[].uses. */
const CATALOG = {
  /* ---- skills ---- */
  '/develop': { kind: 'skill', role: 'Turns a spec into a reviewed, committed branch, autonomously.',
    detail: 'The top-level orchestrator skill. Assesses the input into a config, has a planner write a phase-node plan, then walks it: one executor per phase plus the fixed quality tail (validate, audit, tidy, finalize).' },
  '/plan-work': { kind: 'skill', role: 'Scope any work into a test-driven, phase-node plan.',
    detail: 'Produces the plan + execution strategy that /develop walks. Usable standalone before a manual build. Shares one plan contract + reviewer with /develop.' },
  '/tidy': { kind: 'skill', role: 'Quality gate before pushing.',
    detail: 'Runs a changed-module lint gate, then dispatches a path-routed reviewer set self-scaled to the size of the change. The PT phase is this skill\'s logic.' },
  '/commit-push-watch': { kind: 'skill', role: 'Push, then babysit CI + review until green.',
    detail: 'The handoff target. Opens the PR, extracts and fixes CI failures, resolves review threads, optionally auto-merges. /develop never pushes; it hands off to this.' },

  /* ---- planners ---- */
  'spec-analyzer': { kind: 'agent', arche: 'planner', role: 'Turns specs into validated requirements + file manifest + execution strategy.',
    detail: 'Dispatched when a spec exists. Reads the spec, validates it against the codebase, runs gap analysis, and emits plan sections the orchestrator uses directly, so no follow-up planner is needed.' },
  'plan-explorer': { kind: 'agent', arche: 'planner', role: 'Explore the codebase to scope planned work.',
    detail: 'The no-spec planning path: finds affected layers, reusable patterns, and the closest reference implementation so the plan reuses instead of reinventing.' },
  'plan-reviewer': { kind: 'agent', arche: 'planner', role: 'Fresh-eyes PASS / FAIL on a plan.',
    detail: 'Reads the plan file with zero prior conversation context and runs every completeness check. A FAIL blocks any code from being written: the run terminates as planning-failed.' },

  /* ---- builders ---- */
  'executor (general-purpose)': { kind: 'agent', arche: 'executor', role: 'Runs one plan phase; nests its own children.',
    detail: 'The nesting layer. Inlines its phase\'s nodes verbatim, dispatches writers / test-writers / GAN loops, checks the cheap gates, writes status back to the plan file, and returns a 3-line pointer.' },
  'backend-scaffolder': { kind: 'agent', arche: 'codegen', role: 'Repo + service + controller + module + tests for a new entity.',
    detail: 'Emits production code and its tests in one handoff so the diff-coverage gate is satisfied on the first push.' },
  'ui-codegen': { kind: 'agent', arche: 'codegen', role: 'One UI screen / component, with tests.',
    detail: 'The writer in the UI GAN loop, paired with ui-evaluator for up to 3 write, score, fix iterations.' },
  'backend-test-writer': { kind: 'agent', arche: 'codegen', role: 'Backend repo / service / controller / E2E tests.',
    detail: 'Dispatched alongside production-code agents, and to close specific diff-coverage gaps on uncovered branches (not generic happy-path tests).' },

  /* ---- validators / evaluators ---- */
  'feature-validator': { kind: 'agent', arche: 'validator', role: 'Does the diff actually satisfy every requirement?',
    detail: 'Parse mode turns a spec into a checklist; validate mode diffs the implementation and returns gaps. Rule it lives by: a red/flaky test is a gap to fix, never a missing capability to replan.' },
  'ui-evaluator': { kind: 'agent', arche: 'evaluator', role: 'Scores generated UI against a rubric.',
    detail: 'The discriminator in the GAN loop: PASS with scores, or FAIL with actionable feedback. Deliberately a cheaper tier than the writer it judges, so it stays adversarial rather than collusive.' },

  /* ---- auditors (parallel fan-out leaves) ---- */
  'audit-completeness-checker': { kind: 'agent', arche: 'auditRO', role: 'Cross-layer integration gaps from DB to repo to service to API to UI.',
    detail: 'The broadest lens and the first rung of the audit ladder: the one audit that always runs.' },
  'audit-stubs-scanner': { kind: 'agent', arche: 'auditRO', role: 'Stubs, dead code, unfinished work in the diff.',
    detail: 'Scans for code that was started but not finished, or exists but serves no purpose.' },
  'audit-edge-case-reviewer': { kind: 'agent', arche: 'auditRO', role: 'Missing edge cases + incomplete UX states.',
    detail: 'Audits user-facing behaviour for the states a happy-path build skips: empty, error, loading, boundary.' },
  'audit-regression-checker': { kind: 'agent', arche: 'auditRO', role: 'Functionality lost or silently degraded by the change.',
    detail: 'Traces removed/changed code and its blast radius: the failure mode where a refactor quietly drops behaviour.' },
  'audit-fresh-eyes-reviewer': { kind: 'agent', arche: 'auditRO', role: '"Technically correct, but obviously wrong."',
    detail: 'An unstructured read of every change to catch what a checklist can\'t name. Seeded for UI / visual-mocks work.' },

  /* ---- reviewers (path-routed in tidy) ---- */
  'backend-pattern-reviewer': { kind: 'agent', arche: 'reviewer', role: 'The project\'s backend conventions + runtime hazards.',
    detail: 'Catches architectural violations, API inconsistencies, and test-pattern breaks specialized reviewers don\'t cover.' },
  'ui-reviewer': { kind: 'agent', arche: 'reviewer', role: 'UI: deprecated APIs, duplication, reactive patterns.',
    detail: 'Reviews production UI for component-structure and reactivity issues before they reach CI.' },
  'api-contract-reviewer': { kind: 'agent', arche: 'reviewer', role: 'Bi-directional wire compatibility on API changes.',
    detail: 'Checks new backend against old client AND new client against old backend, so neither side of a rolling deploy breaks. Always included when the API layer is touched.' },

  /* ---- runners ---- */
  'gate runners': { kind: 'agent', arche: 'runner', role: 'Run the heavy build gates for real, in the worktree.',
    detail: 'In the finalize phase, mechanical runners cd into the worktree and run the full suite, multi-target check, coverage, and lint, blocking until green. An absent or all-skipped report is never a pass.' },

  /* ---- tools (provided / conventions: you don't author these) ---- */
  'Tracker MCP': { kind: 'tool', build: 'provided', role: 'Fetch tickets, docs, and attachments.',
    detail: 'An MCP server the harness connects. Agents reach it through tool-search on demand. You configure the connection; you don\'t write a file.' },
  'git: docs branch': { kind: 'tool', build: 'pattern', role: 'Durable, auth-free artifact store.',
    detail: 'An orphan git branch holding heavy design docs and mocks. Sub-agents fetch with `git show`, so no external service can deauth or rate-limit them mid-run. A convention worth stealing.' },
  'git worktree': { kind: 'tool', build: 'provided', role: 'One isolated checkout per run.',
    detail: 'Native git. A branch + working directory per run so parallel agents and the human\'s copy never collide.' },
  'AskUserQuestion': { kind: 'tool', build: 'provided', role: 'The human-in-the-loop prompt.',
    detail: 'A harness tool the orchestrator calls at the clarify seam and at any unresolved gate. The deliberate seams where a human decides.' },

  /* ---- artifacts (produced by the run) ---- */
  'config{}': { kind: 'artifact', build: 'produced', role: 'The run\'s dial-set.',
    detail: 'One object computed in Assess: scope, layers, audit set, retry caps. The same template runs every feature; you tune values, not logic.' },
  'report.md': { kind: 'artifact', build: 'produced', role: 'The run\'s evidence log.',
    detail: 'Findings resolved/accepted/open, escalations, commit SHA, plan-contract gaps. Terminal status is derived from this, never from optimistic prose.' },
  'Green SHA': { kind: 'artifact', build: 'produced', role: 'A clean per-phase commit.',
    detail: 'The rollback-free resume point. The run commits a Green SHA at finalize but never pushes.' },
};

/* The cast, grouped for the section. */
const CAST_GROUPS = [
  { title: 'Skills: playbooks', tone: 'skill', names: ['/develop', '/plan-work', '/tidy', '/commit-push-watch'] },
  { title: 'Planners', tone: 'agent', names: ['spec-analyzer', 'plan-explorer', 'plan-reviewer'] },
  { title: 'Builders & codegen', tone: 'agent', names: ['executor (general-purpose)', 'backend-scaffolder', 'ui-codegen', 'backend-test-writer'] },
  { title: 'Validators & evaluators', tone: 'agent', names: ['feature-validator', 'ui-evaluator'] },
  { title: 'Auditors: parallel fan-out', tone: 'agent', names: ['audit-completeness-checker', 'audit-stubs-scanner', 'audit-edge-case-reviewer', 'audit-regression-checker', 'audit-fresh-eyes-reviewer'] },
  { title: 'Reviewers: path-routed', tone: 'agent', names: ['backend-pattern-reviewer', 'ui-reviewer', 'api-contract-reviewer'] },
];

/* The file anatomy: copy-paste structures, grounded in the real shapes. */
const ANATOMY = [
  {
    id: 'skill', label: 'Skill', tab: 'skill',
    path: '.claude/skills/<name>/SKILL.md',
    code: `---
name: my-pipeline
description: >-
  When to invoke this skill: the exact phrases a user might say.
  This text is matched against the request, so be specific and list
  the negative cases too ("Do NOT trigger for …").
---

# My Pipeline

Steps the orchestrator runs in the main loop:

1. Intake: resolve the argument into source material.
2. Assess: compute one \`config\` the whole run reads.
3. Plan: dispatch a planner; gate on a reviewer PASS.
4. Walk: one executor per phase, then the quality tail.
5. Relay: derive terminal status; hand off.

Heavy detail lives in @.claude/references/*.md, not here.`,
    notes: [
      'Frontmatter is just <code>name</code> + <code>description</code>. The description is the trigger, so write it for matching, not for humans.',
      'The body is the <em>procedure</em>. Keep it skimmable; push long templates and tables into reference files.',
      'A skill orchestrates. It should rarely do heavy work itself; it dispatches agents that do.',
    ],
  },
  {
    id: 'agent', label: 'Agent', tab: 'agent',
    path: '.claude/agents/<name>.md',
    code: `---
name: backend-scaffolder
model: haiku          # cost tier, cheap mechanical to expensive judgement
effort: medium
tools: All tools      # or a tight allowlist: Read, Grep, Glob, Bash
description: >-
  What it does + when the orchestrator should dispatch it.
  This is how the planner decides to route work here.
---

Generate the full backend stack for a new entity (repo, service,
controller, module, tests) following project patterns exactly.

## References
- @.claude/references/backend-scaffolder-templates.md
- @.claude/rules/backend-conventions.md

## What to return
A short pointer. Your final message IS the result, so return data,
not a human-facing summary.`,
    notes: [
      'The <code>model</code> line is cost discipline: cheap models for mechanical work, top tier only for hard judgement.',
      'Scope <code>tools</code> tightly: a read-only reviewer gets <code>Read, Grep, Glob, Bash</code>, not write access.',
      'The body is a system prompt: the job, how to do it, what to return. Link shared templates with <code>@</code>.',
    ],
  },
  {
    id: 'rule', label: 'Rule', tab: 'rule',
    path: '.claude/rules/<name>.md',
    code: `---
paths: '**/*.<ext>'   # auto-loads whenever a matching file is edited
---

# Permission checks belong on the service

Applies to all production source.

Every mutating service method calls \`assertCanWrite(orgId)\`
before any DB write. Avoid permission checks in controllers,
because service-to-service callers bypass them.

Long examples → @.claude/references/permission-patterns.md`,
    notes: [
      'The <code>paths:</code> glob is the whole trick: the rule auto-injects into context only when a matching file is touched.',
      'Lead with the imperative. State the rule, then the focused exclusion. Terse beats thorough.',
      'Rules train the model\'s style as much as they instruct, so write them in the shape you want code comments to take.',
    ],
  },
  {
    id: 'reference', label: 'Reference', tab: 'reference',
    path: '.claude/references/<topic>.md',
    code: `# Backend Scaffolder Templates

Plain markdown, no frontmatter. Pulled in on demand by skills and
agents via @.claude/references/backend-scaffolder-templates.md.

Holds the long-form content that would bury a rule or skill:
  • full multi-file code templates
  • decision trees
  • <examples> sets (happy path, edge case, common wrong shape)

Index it from a parent reference so it stays discoverable.`,
    notes: [
      'No frontmatter, no auto-load. A reference is opt-in: an agent reads it only when a skill/agent/rule links to it.',
      'This is where the bulk lives. It keeps rules and skills short, which keeps the model on-signal.',
    ],
  },
  {
    id: 'plan', label: 'Plan node', tab: 'plan',
    path: 'build/develop/<feature>.plan.md',
    code: `### P3: Order service + controller  [depends: P2] [status: PENDING]
- P3.1 Write OrderService + tests      [agent: backend-scaffolder]
       test-red:com.example.OrderServiceTest   build:backend
- P3.2 Wire OrderController            [agent: general-purpose]
       perm:/v1/orders   w24   cov>=60   DEFERRED-PF
loop: max_iterations 1, commit_on_green

## Execution Log      <!-- append-only crash-recovery journal -->
| Phase | Subtask | Status | Timestamp | Notes |

## Finding Registry   <!-- cross-phase dedup by fingerprint -->
| Fingerprint | Phase | Severity | Status | Note |`,
    notes: [
      'The plan file IS the state. Node <code>[status:]</code> + the Execution Log are authoritative; everything else is derived.',
      'A phase is cohesive: service + controller + DTO + tests is <em>one</em> node, not four. Dependencies gate ordering.',
      'A crashed run resumes by re-reading this file: skip DONE, re-enter the first IN_PROGRESS, reconcile, never regenerate.',
    ],
  },
  {
    id: 'gates', label: 'Gate tokens', tab: 'gates',
    path: 'appended to a plan node',
    code: `test:<FQN>       a named test runs green (forces --rerun, deletes stale XML)
test-red:<FQN>   TDD: test written + observed RED before the prod change
build:<module>   scoped compile of the changed module
cov>=<N>         diff branch-coverage ≥ N%
perm:<route>     auth test exists for the route   (place on the controller node)
w24              transaction threaded across service + controller (grep the diff)
lint:<module>    scoped lint passes
DEFERRED-PF      too heavy to run inline; re-run in the Finalize phase`,
    notes: [
      'A gate passes because a <strong>command ran and produced evidence</strong>, not because an agent decided it looked done.',
      'Placement is load-bearing: <code>perm:</code> on the controller node, <code>w24</code> across service + controller.',
      'Tag anything heavy <code>DEFERRED-PF</code> so the executor stays fast and the finalize phase runs it for real.',
    ],
  },
];

/* ----------------------------- rendering ----------------------------- */
const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const KIND_LABEL = { skill: 'skill', agent: 'agent', tool: 'tool', artifact: 'artifact' };

function renderCast() {
  const wrap = document.querySelector('#cast-groups');
  if (!wrap) return;
  CAST_GROUPS.forEach((g) => {
    const grp = document.createElement('div');
    grp.className = 'cast-group';
    const cards = g.names.map((name) => {
      const e = CATALOG[name];
      if (!e) return '';
      return `<button class="cast-card chip-${e.kind}" data-cat="${name}">
        <span class="cast-kind">${KIND_LABEL[e.kind]}</span>
        <span class="cast-name">${name}</span>
        <span class="cast-role">${e.role}</span>
        <span class="cast-go">what to build →</span>
      </button>`;
    }).join('');
    grp.innerHTML = `<h3 class="cast-title">${g.title}</h3><div class="cast-cards">${cards}</div>`;
    wrap.appendChild(grp);
  });
  wrap.addEventListener('click', (e) => {
    const card = e.target.closest('.cast-card[data-cat]');
    if (card) openCatalog(card.dataset.cat);
  });
}

function buildGuidance(e) {
  if (e.kind === 'skill') {
    return `<div class="modal-build">
      <div class="mb-head">How you'd build one <span class="mb-path">.claude/skills/&lt;name&gt;/SKILL.md</span></div>
      <p>A <b>name</b> + <b>description</b> frontmatter (the description is the trigger), then the procedure as numbered steps. Heavy detail lives in references.</p>
      <a class="mb-link" href="#anatomy" data-tab="skill">See the full skill template ↓</a>
    </div>`;
  }
  if (e.kind === 'agent') {
    const a = ARCHETYPE[e.arche] || {};
    return `<div class="modal-build">
      <div class="mb-head">How you'd build one <span class="mb-path">.claude/agents/&lt;name&gt;.md</span></div>
      <div class="mb-spec">
        <span><b>model</b> ${a.model || '-'}</span>
        <span><b>tools</b> ${a.tools || '-'}</span>
      </div>
      <p>${a.note || ''}</p>
      <a class="mb-link" href="#anatomy" data-tab="agent">See the full agent template ↓</a>
    </div>`;
  }
  const msg = {
    provided: 'Provided by the harness: you configure access, you don\'t author a file.',
    pattern: 'A convention, not a file. Adopt the pattern (here: an orphan git branch for durable artifacts).',
    produced: 'Produced by the run, not authored. You define its shape inside your skill or plan file.',
  }[e.build] || '';
  return `<div class="modal-build"><div class="mb-head">Where it comes from</div><p>${msg}</p></div>`;
}

function openCatalog(name) {
  const e = CATALOG[name];
  const modal = document.querySelector('#modal');
  const body = document.querySelector('#modal-body');
  if (!e) {
    body.innerHTML = `<h3>${name}</h3><p class="modal-role">No catalog entry yet.</p>`;
  } else {
    body.innerHTML = `
      <span class="modal-kind chip-${e.kind}">${KIND_LABEL[e.kind]}</span>
      <h3>${name}</h3>
      <p class="modal-role">${e.role}</p>
      <p class="modal-detail">${e.detail}</p>
      ${buildGuidance(e)}`;
  }
  modal.hidden = false;
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  const modal = document.querySelector('#modal');
  if (modal) modal.hidden = true;
  document.body.style.overflow = '';
}

// Opt-in deep-dives launched from a "→" chip: keep the table terse, park the detail here.
const INSIGHTS = {
  fanout: {
    kicker: 'the deeper why · measured medians, reasoned mechanics',
    title: 'Why the fan-out runs hot, and why the skill bounds it',
    body: `
      <p class="insight-lede">Median spend is close across all four methods. What separates them is <strong>who holds the fan-out lever</strong>, and the cache mechanics underneath.</p>
      <div class="insight-row">
        <h4>Run-time vs author-time control</h4>
        <p>Dynamic Workflow lets the <em>model</em> choose the fan-out shape live: "spawn 16 finders × 3 verifiers to be safe." Nothing caps that instinct, so spend has no ceiling. The SubDriven skill fixes the shape at <em>authoring</em> time. Phases, dispatch, the gate ladder, and the self-scaling reviewer count are all tuned before the run, so the model can't conjure five more verifiers mid-flight. <strong>That makes the predictability structural.</strong></p>
      </div>
      <div class="insight-row">
        <h4>The cache tax is real, but it cuts the other way</h4>
        <p>A fresh agent writes its prefix to cache at a ~1.25× premium; a warm read bills ~1/10. So "new agent every time" <em>does</em> pay a cold tax. But the bigger cost is the opposite: one long <strong>resumed</strong> context re-reads its whole, ever-growing cache every turn, which is why <strong>Vanilla is the heaviest median despite being a single agent</strong>. Fan-out's agents each read <em>small</em> contexts, and identical siblings share a warm prefix: spawn 16 refuters, one writes the cache, fifteen read it warm. The tax amortizes when the fan-out is homogeneous.</p>
      </div>
      <div class="insight-row">
        <h4>Where it bites Dynamic Workflow</h4>
        <p>Its fan-out is <em>heterogeneous and decided live</em>: many different prompts, each a unique cold prefix. If the script stalls between waves, the 5-minute cache TTL lapses and the next wave pays cold again. The skill's fixed, phased dispatch keeps shared prefixes (CLAUDE.md, the standard agent briefs) hot and reused, for better cache locality and tighter spend.</p>
      </div>
      <p class="insight-foot"><strong>Measured:</strong> effective tokens per run, representative figures from a real project's runs (anonymized). <strong>Reasoned:</strong> the cache mechanics above are directional, from architecture plus the documented 5-minute cache TTL and ~1.25× / ~0.1× write / read rates.</p>`,
  },
};

function openInsight(key) {
  const e = INSIGHTS[key];
  if (!e) return;
  const modal = document.querySelector('#modal');
  const body = document.querySelector('#modal-body');
  if (!modal || !body) return;
  body.innerHTML = `
    <span class="modal-kind insight-kind">${e.kicker}</span>
    <h3>${e.title}</h3>
    ${e.body}`;
  modal.hidden = false;
  document.body.style.overflow = 'hidden';
}

function renderAnatomy() {
  const tabs = document.querySelector('#anatomy-tabs');
  const panel = document.querySelector('#anatomy-panel');
  if (!tabs || !panel) return;
  tabs.innerHTML = ANATOMY.map((a, i) =>
    `<button class="anatomy-tab${i === 0 ? ' active' : ''}" data-id="${a.id}">${a.label}</button>`).join('');

  const show = (id) => {
    const a = ANATOMY.find((x) => x.id === id) || ANATOMY[0];
    panel.innerHTML = `
      <div class="anatomy-filepath"><span>file</span>${a.path}</div>
      <pre class="anatomy-code"><code>${esc(a.code)}</code></pre>
      <ul class="anatomy-notes">${a.notes.map((n) => `<li>${n}</li>`).join('')}</ul>`;
    tabs.querySelectorAll('.anatomy-tab').forEach((t) => t.classList.toggle('active', t.dataset.id === id));
  };
  tabs.addEventListener('click', (e) => {
    const t = e.target.closest('.anatomy-tab');
    if (t) show(t.dataset.id);
  });
  show(ANATOMY[0].id);

  // "See the full template" links inside the modal: close, switch tab, scroll to it.
  document.addEventListener('click', (e) => {
    const link = e.target.closest('.mb-link[data-tab]');
    if (!link) return;
    e.preventDefault();
    closeModal();
    setTimeout(() => {
      show(link.dataset.tab);
      document.querySelector('#anatomy')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 90);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  renderCast();
  renderAnatomy();
  const modal = document.querySelector('#modal');
  if (modal) {
    modal.addEventListener('click', (e) => { if (e.target === modal || e.target.closest('.modal-close')) closeModal(); });
  }
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });
});

window.openCatalog = openCatalog;
window.openInsight = openInsight;
