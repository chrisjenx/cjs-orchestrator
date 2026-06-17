/* =========================================================================
 * Watch it run — animated TREE of one /develop run, stepped agent-by-agent.
 * PUBLIC REPO — `META` uses generic role names; keep them stack-neutral. See /CLAUDE.md.
 * The orchestrator walks phases left→right (the trunk); each phase's agents
 * hang BELOW it. Stepping drills into each agent and calls out its
 * name · model · effort · role. Only the active phase expands; finished
 * phases collapse to a ✓.
 *
 * ACCURACY (modelled on the real skill, not invented):
 *  - Discovery always fans out 4 finders; the planner forks CANDIDATES only at
 *    raised intensity; the audit STARTS with completeness and climbs only on a
 *    defect round; agent counts are EXPECTED seeds, never caps.
 *  - The GAN loop is run BY the executor: it dispatches the writer (a leaf),
 *    takes the result to the evaluator (a leaf), and re-dispatches the writer
 *    with feedback, up to 3×. The writer does not spawn the evaluator.
 *  - model · effort shown per each agent's OWN definition (.claude/agents/*.md);
 *    inside /develop the orchestrator may pass an explicit tier-map model.
 * ========================================================================= */

const PLAN_LEAN = [
  { id: 'disc', label: 'Tier-0 discover', kind: 'mechanical' },
  { id: 't1', label: 'Tier-1 finders', kind: 'finder', badge: 'parallel ×4', children: [
    { id: 'reuse', label: 'reuse', kind: 'finder' }, { id: 'ref', label: 'reference', kind: 'finder' },
    { id: 'scope', label: 'scope', kind: 'finder' }, { id: 'q', label: 'questions', kind: 'finder' },
  ] },
  { id: 'judge', label: 'Tier-2 judge', kind: 'judge' },
  { id: 'prev', label: 'plan-reviewer', kind: 'gate', badge: 'PASS gate' },
];
const PF_SUB = [{ id: 'run', label: 'gate runners', kind: 'gate', children: [{ id: 'sha', label: 'Green SHA', kind: 'artifact' }] }];

const SCENARIOS = {
  small: {
    label: 'Small', files: '≤5 files · 1 layer', agents: '≈28',
    blurb: 'e.g. a few endpoints on an already-tested service. New work, not surface area, sizes it.',
    phases: [
      { id: 'plan', label: 'Plan', flow: 'mixed',
        say: '<b>Plan.</b> A mechanical scan, then <b>four finders run in parallel</b>. One judge synthesizes a phase-node plan — <b>plan-reviewer</b> must PASS or the run stops as <code>planning-failed</code>.', sub: PLAN_LEAN },
      { id: 'p1', label: 'P1 · service', flow: 'nest',
        say: '<b>P1.</b> One executor for the phase. A small single-file slice → <b>one writer</b> (flat is correct), writing prod + tests together. Only <b>cheap gates</b> run here.',
        sub: [{ id: 'exec', label: 'executor', kind: 'executor', children: [{ id: 'sc', label: 'backend-scaffolder', kind: 'writer' }] }] },
      { id: 'pv', label: 'PV · validate', flow: 'skip', skip: true,
        say: '<b>PV — Validate.</b> Small, clean scope with no enumerated test list → the prose validator is <b>skipped</b>. The mechanical <b>acceptance gates still run</b> — validation is never fully off.' },
      { id: 'pa', label: 'PA · audit', flow: 'single',
        say: '<b>PA — Audit.</b> Starts with <b>one</b> agent: completeness. A clean round <b>passes</b> — the ladder climbs only when a round finds a defect.',
        sub: [{ id: 'comp', label: 'completeness', kind: 'audit', badge: 'always-on' }] },
      { id: 'pt', label: 'PT · tidy', flow: 'fork',
        say: '<b>PT — Tidy.</b> Changed-module lint first, then a <b>path-routed</b> reviewer set, self-scaled to the change.',
        sub: [{ id: 'dk', label: 'lint', kind: 'gate', badge: 'gate' }, { id: 'bp', label: 'backend-pattern-reviewer', kind: 'reviewer' }] },
      { id: 'pf', label: 'PF · finalize', flow: 'nest',
        say: '<b>PF — Finalize.</b> Every deferred heavy gate runs for real — full suite, coverage, multi-target. Commit a <b>Green SHA</b>. <b>No push.</b>', sub: PF_SUB },
    ],
  },
  medium: {
    label: 'Medium', files: 'the middle band', agents: '≈52',
    blurb: 'multiple files across 2–3 layers — a backend slice, its client binding, a screen. No fixed file threshold; the band between small and large.',
    phases: [
      { id: 'plan', label: 'Plan', flow: 'mixed',
        say: '<b>Plan.</b> Same lean discovery: four parallel finders → one judge → plan-reviewer PASS. The planner does <b>not</b> fork candidates at default intensity.', sub: PLAN_LEAN },
      { id: 'p1', label: 'P1 · backend', flow: 'nest',
        say: '<b>P1 · backend.</b> The executor nests its own children — a scaffolder + a test-writer, prod and tests together. P1 and P2 touch <b>disjoint files</b>, so they can dispatch in parallel (one executor per walk step).',
        sub: [{ id: 'exec', label: 'executor', kind: 'executor', children: [{ id: 'sc', label: 'backend-scaffolder', kind: 'writer' }, { id: 'tw', label: 'backend-test-writer', kind: 'writer' }] }] },
      { id: 'p2', label: 'P2 · client API', flow: 'nest',
        say: '<b>P2 · client API.</b> A scoped codegen leaf writes the client stamp + its mock test. Glue would route to general-purpose; an artifact-shaped file routes to its named writer.',
        sub: [{ id: 'exec', label: 'executor', kind: 'executor', children: [{ id: 'ca', label: 'client-api-codegen', kind: 'writer' }] }] },
      { id: 'p3', label: 'P3 · UI screen', flow: 'loop',
        say: '<b>P3 · UI.</b> The <b>executor runs a GAN loop</b>: it dispatches the writer, takes the component to the evaluator, then re-dispatches the writer with the feedback — <b>up to 3 iterations, one component per loop</b>. The writer and evaluator are both the executor\'s leaves.',
        sub: [{ id: 'exec', label: 'executor', kind: 'executor', children: [{ id: 'w', label: 'ui-codegen', kind: 'writer' }, { id: 'e', label: 'ui-evaluator', kind: 'evaluator' }] }] },
      { id: 'pv', label: 'PV · validate', flow: 'single',
        say: '<b>PV — Validate.</b> feature-validator diffs the build against the requirements table. A gap becomes a <b>fix-in-place</b> back-edge; a red or flaky test is a gap, never a missing capability.',
        sub: [{ id: 'fv', label: 'feature-validator', kind: 'judge' }] },
      { id: 'pa', label: 'PA · audit', flow: 'climb',
        say: '<b>PA — Audit.</b> completeness runs first and <b>finds a defect</b> → the ladder climbs one rung to <b>+stubs</b>. Each round\'s seeded set runs in parallel; the climb is reactive — one rung per defect-finding round.',
        sub: [{ id: 'comp', label: 'completeness', kind: 'audit', badge: 'always-on' }, { id: 'stubs', label: 'stubs', kind: 'audit-cond', badge: '+rung' }] },
      { id: 'pt', label: 'PT · tidy', flow: 'fork',
        say: '<b>PT — Tidy.</b> Lint, then <b>path-routed reviewers in parallel</b>, scaled to the change. api-contract-reviewer is mandatory whenever <code>the API layer</code> is touched.',
        sub: [{ id: 'dk', label: 'lint', kind: 'gate', badge: 'gate' }, { id: 'bp', label: 'backend-pattern-reviewer', kind: 'reviewer' }, { id: 'cu', label: 'ui-reviewer', kind: 'reviewer' }, { id: 'ac', label: 'api-contract-reviewer', kind: 'reviewer' }] },
      { id: 'pf', label: 'PF · finalize', flow: 'nest',
        say: '<b>PF — Finalize.</b> All deferred heavy gates run for real, blocking until green. Commit a <b>Green SHA</b>. No push.', sub: PF_SUB },
    ],
  },
  large: {
    label: 'Large', files: '≥20 files · ≥4 layers', agents: '≈110',
    blurb: 'a high-risk feature across backend, storage, shared API, and UI — intensity raised, new risk logic triggers a framed re-audit. (Most tickets are small or medium; large is rare.)',
    phases: [
      { id: 'plan', label: 'Plan', flow: 'candfork',
        say: '<b>Plan.</b> Four finders fan out as always — but here, with <b>intensity raised</b>, the judge <b>forks into candidates</b> (reuse-first · risk-first · simplicity-first) and a synthesizer picks the best. Default runs do <b>not</b> fork; this is the raised-intensity path.',
        sub: [
          { id: 'disc', label: 'Tier-0 discover', kind: 'mechanical' },
          { id: 't1', label: 'Tier-1 finders', kind: 'finder', badge: 'parallel ×4', children: [
            { id: 'reuse', label: 'reuse', kind: 'finder' }, { id: 'ref', label: 'reference', kind: 'finder' },
            { id: 'scope', label: 'scope', kind: 'finder' }, { id: 'q', label: 'questions', kind: 'finder' } ] },
          { id: 'cand', label: 'Tier-2 candidates', kind: 'candidate', badge: 'fork', children: [
            { id: 'c1', label: 'reuse-first', kind: 'candidate' }, { id: 'c2', label: 'risk-first', kind: 'candidate' }, { id: 'c3', label: 'simplicity-first', kind: 'candidate' } ] },
          { id: 'synth', label: 'synthesizer', kind: 'judge' },
          { id: 'prev', label: 'plan-reviewer', kind: 'gate', badge: 'PASS gate' },
        ] },
      { id: 'p1', label: 'P1 · backend', flow: 'nest',
        say: '<b>P1 · backend.</b> Executor nests a scaffolder + test-writer. Disjoint phases dispatch in parallel waves; phases that share files serialize.',
        sub: [{ id: 'exec', label: 'executor', kind: 'executor', children: [{ id: 'sc', label: 'backend-scaffolder', kind: 'writer' }, { id: 'tw', label: 'backend-test-writer', kind: 'writer' }] }] },
      { id: 'p2', label: 'P2 · storage', flow: 'nest',
        say: '<b>P2 · storage.</b> A storage codegen leaf writes the dual implementations + DI bindings.',
        sub: [{ id: 'exec', label: 'executor', kind: 'executor', children: [{ id: 'ks', label: 'storage-codegen', kind: 'writer' }] }] },
      { id: 'p3', label: 'P3 · shared API', flow: 'parwriters',
        say: '<b>P3 · shared API.</b> A compile-atomic multi-file slice → the executor fans out <b>parallel per-file writers</b> + a test-writer, then runs <b>one compile at the slice boundary</b>. Writer fan-out is scale-gated.',
        sub: [{ id: 'exec', label: 'executor', kind: 'executor', children: [{ id: 'wa', label: 'writer · file A', kind: 'writer' }, { id: 'wb', label: 'writer · file B', kind: 'writer' }, { id: 'tw', label: 'test-writer', kind: 'writer' }] }] },
      { id: 'p4', label: 'P4 · UI', flow: 'loop',
        say: '<b>P4 · UI.</b> The executor runs a GAN loop — it dispatches ui-codegen, scores it with ui-evaluator, and re-dispatches with feedback, up to 3 iterations.',
        sub: [{ id: 'exec', label: 'executor', kind: 'executor', children: [{ id: 'w', label: 'ui-codegen', kind: 'writer' }, { id: 'e', label: 'ui-evaluator', kind: 'evaluator' }] }] },
      { id: 'p5', label: 'P5 · UI', flow: 'loop',
        say: '<b>P5 · UI.</b> A second screen, its own GAN loop. UI / visual-mocks scope also seeds <b>fresh-eyes</b> in the audit up front.',
        sub: [{ id: 'exec', label: 'executor', kind: 'executor', children: [{ id: 'w', label: 'ui-codegen', kind: 'writer' }, { id: 'e', label: 'ui-evaluator', kind: 'evaluator' }] }] },
      { id: 'pv', label: 'PV · validate', flow: 'single',
        say: '<b>PV — Validate.</b> feature-validator checks the diff against every requirement. ITERATE converts each gap to a fix-in-place back-edge and re-walks, bounded by a retry cap.',
        sub: [{ id: 'fv', label: 'feature-validator', kind: 'judge' }] },
      { id: 'pa', label: 'PA · audit', flow: 'wide',
        say: '<b>PA — Audit.</b> New risk logic (permission / the domain / migration) triggers a <b>framed re-audit</b>: regression + fresh-eyes are <b>pre-seeded</b>, and the ladder also climbs completeness → stubs → edge-case. All seeded auditors run in parallel.',
        sub: [{ id: 'comp', label: 'completeness', kind: 'audit', badge: 'always-on' }, { id: 'stubs', label: 'stubs', kind: 'audit-cond' }, { id: 'edge', label: 'edge-case', kind: 'audit-cond' }, { id: 'reg', label: 'regression', kind: 'audit-cond', badge: 'framed' }, { id: 'fe', label: 'fresh-eyes', kind: 'audit-cond', badge: 'framed' }] },
      { id: 'pt', label: 'PT · tidy', flow: 'fork',
        say: '<b>PT — Tidy.</b> A larger path-routed reviewer set in parallel — backend, UI, portability across targets, and api-contract (mandatory, the API layer is touched).',
        sub: [{ id: 'dk', label: 'lint', kind: 'gate', badge: 'gate' }, { id: 'bp', label: 'backend-pattern-reviewer', kind: 'reviewer' }, { id: 'cu', label: 'ui-reviewer', kind: 'reviewer' }, { id: 'kt', label: 'portability-reviewer', kind: 'reviewer' }, { id: 'ac', label: 'api-contract-reviewer', kind: 'reviewer' }] },
      { id: 'pf', label: 'PF · finalize', flow: 'nest',
        say: '<b>PF — Finalize.</b> Every deferred heavy gate runs for real, blocking until green; empty coverage is never a pass. Commit a <b>Green SHA</b>. No push.', sub: PF_SUB },
    ],
  },
};

/* model · effort · role per agent. Named agents = their own definition frontmatter;
   orchestrator roles (executor, finders, judge…) = the /develop tier-map model. */
const META = {
  'Tier-0 discover':    { agent: 'discover (mechanical)', model: 'haiku', effort: '—', role: 'Runs the reuse-map scan (discover.py).' },
  'Tier-1 finders':     { agent: 'Tier-1 finders', model: 'sonnet', effort: '—', role: 'Spawns four parallel evidence finders.' },
  reuse:                { agent: 'plan:find:reuse', model: 'sonnet', effort: '—', role: 'Behavioural-equivalence / reuse check.' },
  reference:            { agent: 'plan:find:reference', model: 'sonnet', effort: '—', role: 'Closest reference feature\'s layer trace.' },
  scope:                { agent: 'plan:find:scope', model: 'sonnet', effort: '—', role: 'Which layers are in / out, and why.' },
  questions:            { agent: 'plan:find:questions', model: 'sonnet', effort: '—', role: 'Under-determined decisions to surface.' },
  'Tier-2 judge':       { agent: 'plan-explorer / spec-analyzer', model: 'opus', effort: '—', role: 'Synthesizes the phase-node plan.' },
  'Tier-2 candidates':  { agent: 'judge (forked)', model: 'opus', effort: '—', role: 'Forks competing plan candidates.' },
  'reuse-first':        { agent: 'plan candidate', model: 'opus', effort: '—', role: 'Plan, reuse-first angle.' },
  'risk-first':         { agent: 'plan candidate', model: 'opus', effort: '—', role: 'Plan, risk-first angle.' },
  'simplicity-first':   { agent: 'plan candidate', model: 'opus', effort: '—', role: 'Plan, simplicity-first angle.' },
  synthesizer:          { agent: 'synthesizer', model: 'opus', effort: '—', role: 'Picks the best candidate.' },
  'plan-reviewer':      { agent: 'plan-reviewer', model: 'sonnet', effort: 'max', role: 'Fresh-eyes PASS / FAIL gate on the plan.' },
  executor:             { agent: 'executor (general-purpose)', model: 'sonnet', effort: '—', role: 'Runs the phase; nests its own children.' },
  'backend-scaffolder': { agent: 'backend-scaffolder', model: 'haiku', effort: 'medium', role: 'Repo + service + controller + tests for an entity.' },
  'backend-test-writer':{ agent: 'backend-test-writer', model: 'haiku', effort: 'medium', role: 'Backend tests; closes coverage gaps.' },
  'client-api-codegen': { agent: 'client-api-codegen', model: 'haiku', effort: 'medium', role: 'Client API stamp + mock-engine test.' },
  'storage-codegen':    { agent: 'storage-codegen', model: 'haiku', effort: 'medium', role: 'Shared storage impls + DI bindings.' },
  'ui-codegen':         { agent: 'ui-codegen', model: 'opus', effort: 'medium', role: 'Writes one UI component + tests.' },
  'ui-evaluator':       { agent: 'ui-evaluator', model: 'sonnet', effort: 'medium', role: 'Scores the UI vs a rubric — the GAN discriminator.' },
  'writer · file A':    { agent: 'per-file writer', model: 'sonnet', effort: '—', role: 'One file of a compile-atomic slice.' },
  'writer · file B':    { agent: 'per-file writer', model: 'sonnet', effort: '—', role: 'One file of a compile-atomic slice.' },
  'test-writer':        { agent: 'backend-test-writer', model: 'haiku', effort: 'medium', role: 'Tests for the slice.' },
  'feature-validator':  { agent: 'feature-validator', model: 'opus', effort: 'medium', role: 'Diffs the build against the requirements table.' },
  completeness:         { agent: 'audit-completeness-checker', model: 'sonnet', effort: 'high', role: 'Cross-layer integration gaps (DB→…→UI).' },
  stubs:                { agent: 'audit-stubs-scanner', model: 'haiku', effort: 'low', role: 'Stubs / dead code in the diff.' },
  'edge-case':          { agent: 'audit-edge-case-reviewer', model: 'sonnet', effort: 'medium', role: 'Missing edge cases + UX states.' },
  regression:           { agent: 'audit-regression-checker', model: 'sonnet', effort: 'high', role: 'Lost / silently degraded behaviour.' },
  'fresh-eyes':         { agent: 'audit-fresh-eyes-reviewer', model: 'sonnet', effort: 'medium', role: '"Correct, but obviously wrong."' },
  lint:                 { agent: 'lint', model: '—', effort: '—', role: 'Changed-module lint gate.' },
  'backend-pattern-reviewer': { agent: 'backend-pattern-reviewer', model: 'sonnet', effort: 'low', role: 'Backend conventions + runtime hazards.' },
  'ui-reviewer':        { agent: 'ui-reviewer', model: 'sonnet', effort: 'low', role: 'UI conventions + reactivity.' },
  'api-contract-reviewer': { agent: 'api-contract-reviewer', model: 'haiku', effort: 'low', role: 'Bi-directional wire compatibility.' },
  'portability-reviewer':{ agent: 'portability-reviewer', model: 'haiku', effort: 'low', role: 'Cross-target portability.' },
  'gate runners':       { agent: 'gate runners', model: 'haiku', effort: '—', role: 'Run the heavy build gates, blocking.' },
  'Green SHA':          { agent: 'Green SHA', model: '—', effort: '—', role: 'The clean per-phase commit (no push).' },
};
const metaFor = (label) => META[label] || { agent: label, model: '—', effort: '—', role: '' };

const FLOW_LEGEND = [
  { tone: 'nest', label: 'nest — executor spawns its own agents' },
  { tone: 'fork', label: 'fork / fan-out — agents run in parallel' },
  { tone: 'gate', label: 'gate — passes on evidence' },
  { tone: 'cond', label: 'conditional — fires only on its trigger' },
];
const SHORT = {
  'backend-scaffolder': 'scaffolder', 'backend-test-writer': 'test-writer', 'client-api-codegen': 'client-api',
  'ui-codegen': 'ui-codegen', 'ui-evaluator': 'ui-evaluator', 'storage-codegen': 'storage',
  'feature-validator': 'validator', 'backend-pattern-reviewer': 'backend-rev', 'ui-reviewer': 'ui-rev',
  'api-contract-reviewer': 'api-contract', 'portability-reviewer': 'portability-rev', 'plan-reviewer': 'plan-review',
  'Tier-0 discover': 'discover', 'Tier-1 finders': 'finders', 'Tier-2 judge': 'judge', 'Tier-2 candidates': 'candidates',
  'synthesizer': 'synth', 'writer · file A': 'writer A', 'writer · file B': 'writer B', 'gate runners': 'gate runners',
};
const short = (l) => SHORT[l] || l;
const MODEL_WORDS = new Set(['haiku', 'sonnet', 'opus']);

/* geometry */
const VH = 360, TRUNK_Y = 106, ENTRY_Y = 48, PHASE_GAP = 156, START_X = 176, LEVEL_GAP = 88, LEAF_GAP = 134, SIDE_PAD = 74;
const SVGNS = 'http://www.w3.org/2000/svg';

function layoutSub(roots) {
  let leaf = 0;
  const place = (node, depth) => {
    node._depth = depth;
    if (node.children && node.children.length) {
      const xs = node.children.map((c) => place(c, depth + 1));
      node._rx = xs.reduce((a, b) => a + b, 0) / xs.length;
    } else node._rx = leaf++;
    return node._rx;
  };
  const vroot = { children: roots };
  place(vroot, 0);
  return { vroot, leaves: Math.max(1, leaf) };
}

/* Flatten a phase into ordered steps: a phase-intro, then one step per agent
   (pre-order). GAN phases become explicit writer⇄evaluator iterations. */
function buildSteps(scenario) {
  const steps = [];
  SCENARIOS[scenario].phases.forEach((p, pi) => {
    steps.push({ kind: 'phase', p, pi });
    if (p.skip || !p.sub) return;
    if (p.flow === 'loop') {
      const exec = p.sub[0]; const w = exec.children[0]; const e = exec.children[1];
      steps.push({ kind: 'agent', p, pi, id: exec.id, label: exec.label });
      steps.push({ kind: 'agent', p, pi, id: w.id, label: w.label, iter: 'iteration 1', tag: 'writes the component' });
      steps.push({ kind: 'agent', p, pi, id: e.id, label: e.label, iter: 'iteration 1', tag: 'scores it — needs a fix' });
      steps.push({ kind: 'agent', p, pi, id: w.id, label: w.label, iter: 'iteration 2', tag: 'revises with the feedback' });
      steps.push({ kind: 'agent', p, pi, id: e.id, label: e.label, iter: 'iteration 2', tag: 'scores it — PASS' });
      return;
    }
    const walk = (nodes) => nodes.forEach((n) => { steps.push({ kind: 'agent', p, pi, id: n.id, label: n.label }); if (n.children) walk(n.children); });
    walk(p.sub);
  });
  return steps;
}

function initFlow() {
  const stage = document.querySelector('#flow-stage');
  if (!stage) return;
  const narration = document.querySelector('#flow-narration');
  const callout = document.querySelector('#flow-callout');
  const progress = document.querySelector('#flow-progress');
  const playBtn = document.querySelector('#flow-play');
  const countEl = document.querySelector('#flow-count');
  const legend = document.querySelector('#flow-legend');
  if (legend) legend.innerHTML = FLOW_LEGEND.map((l) => `<span class="flk t-${l.tone}"><i></i>${l.label}</span>`).join('');
  const scWrap = document.querySelector('#flow-scenarios');
  if (scWrap) scWrap.innerHTML = Object.entries(SCENARIOS).map(([k, s], i) =>
    `<button class="flow-sc${i === 0 ? ' active' : ''}" data-sc="${k}">${s.label}<span>${s.files}</span></button>`).join('');

  const canvas = document.createElement('div');
  canvas.className = 'flow-canvas';
  const svg = document.createElementNS(SVGNS, 'svg');
  svg.setAttribute('class', 'flow-edges'); svg.setAttribute('preserveAspectRatio', 'none');
  canvas.appendChild(svg); stage.appendChild(canvas);

  let scenario = 'small', phaseEls = {}, steps = [], virtualW = 1000, token = null, cur = 0, timer = null;

  function mkNode(id, label, kind, x, y, badge, cls, full) {
    const d = document.createElement('div');
    d.className = `flow-node fn-${kind}${cls ? ' ' + cls : ''}`;
    d.dataset.id = id; d.style.left = `${x}px`; d.style.top = `${y}px`;
    if (full && full !== label) d.title = full;
    d.innerHTML = `<span class="fn-dot"></span><span class="fn-label">${label}</span>${badge ? `<span class="fn-badge">${badge}</span>` : ''}`;
    canvas.appendChild(d); return d;
  }
  function mkEdge(x1, y1, x2, y2, cls, path) {
    const e = document.createElementNS(SVGNS, path ? 'path' : 'line');
    if (path) { e.setAttribute('d', path); e.setAttribute('fill', 'none'); }
    else { e.setAttribute('x1', x1); e.setAttribute('y1', y1); e.setAttribute('x2', x2); e.setAttribute('y2', y2); }
    e.setAttribute('class', `flow-edge${cls ? ' ' + cls : ''}`); e.setAttribute('vector-effect', 'non-scaling-stroke');
    svg.appendChild(e); return e;
  }

  function render() {
    [...canvas.querySelectorAll('.flow-node, .flow-token')].forEach((n) => n.remove());
    svg.innerHTML = ''; phaseEls = {}; token = null;
    const sc = SCENARIOS[scenario]; const phases = sc.phases;
    steps = buildSteps(scenario);
    virtualW = START_X + (phases.length - 1) * PHASE_GAP + 150;
    canvas.style.width = `${virtualW}px`; canvas.style.height = `${VH}px`;
    svg.setAttribute('viewBox', `0 0 ${virtualW} ${VH}`); svg.setAttribute('width', virtualW); svg.setAttribute('height', VH);
    if (countEl) countEl.innerHTML = `<span class="fc-n">${sc.agents}</span> agents (expected) · <span class="fc-b">${sc.blurb}</span>`;

    mkNode('dev', '/develop', 'skill', START_X - 120, ENTRY_Y, null, 'entry');
    mkNode('orch', 'Orchestrator', 'orch', START_X, ENTRY_Y, null, 'entry');
    mkEdge(START_X - 120, ENTRY_Y, START_X, ENTRY_Y, 'lit-entry');
    mkEdge(START_X, ENTRY_Y + 13, START_X, TRUNK_Y - 12, 'lit-entry');

    let prevX = null;
    phases.forEach((p, i) => {
      const px = START_X + i * PHASE_GAP;
      if (prevX != null) mkEdge(prevX, TRUNK_Y, px, TRUNK_Y, 'trunk lit-entry');
      const node = mkNode(p.id, p.label, 'phase', px, TRUNK_Y, null, 'trunk-node' + (p.skip ? ' fn-skip' : ''));
      const wide = ['fork', 'wide', 'candfork', 'parwriters'].includes(p.flow);
      const entry = { node, px, wide, sub: {}, edgeByChild: {}, loopEdge: null };
      if (p.sub) {
        const { vroot, leaves } = layoutSub(p.sub);
        const half = (leaves - 1) / 2;
        let origin = px - half * LEAF_GAP;
        if (origin < SIDE_PAD) origin = SIDE_PAD;
        if (origin + (leaves - 1) * LEAF_GAP > virtualW - SIDE_PAD) origin = virtualW - SIDE_PAD - (leaves - 1) * LEAF_GAP;
        const walk = (n, parentX, parentY) => {
          (n.children || []).forEach((c) => {
            const cx = origin + c._rx * LEAF_GAP, cy = TRUNK_Y + c._depth * LEVEL_GAP;
            const badge = MODEL_WORDS.has(c.badge) ? null : c.badge;
            const el = mkNode(`${p.id}-${c.id}`, short(c.label), c.kind, cx, cy, badge, 'sub-node', c.label);
            entry.sub[c.id] = el;
            entry.edgeByChild[c.id] = mkEdge(parentX, parentY + 12, cx, cy - 11, 'sub' + (c.kind === 'audit-cond' ? ' cond' : ''));
            walk(c, cx, cy);
          });
        };
        walk(vroot, px, TRUNK_Y);
        if (p.flow === 'loop') {
          const w = entry.sub[p.sub[0].children[0].id], e = entry.sub[p.sub[0].children[1].id];
          const wx = parseFloat(w.style.left), ex = parseFloat(e.style.left), ly = parseFloat(w.style.top);
          entry.loopEdge = mkEdge(0, 0, 0, 0, 'gan', `M ${wx} ${ly + 13} Q ${(wx + ex) / 2} ${ly + 52} ${ex} ${ly + 13}`);
        }
      }
      phaseEls[p.id] = entry; prevX = px;
    });
    go(0);
  }

  function ensureToken() { if (!token) { token = document.createElement('div'); token.className = 'flow-token'; canvas.appendChild(token); } return token; }
  function moveToken(x, y, instant) {
    const t = ensureToken();
    if (instant) t.style.transition = 'none';
    t.style.left = `${x}px`; t.style.top = `${y}px`;
    if (instant) { void t.offsetWidth; t.style.transition = ''; }
  }
  const xy = (el) => ({ x: parseFloat(el.style.left), y: parseFloat(el.style.top) });

  function setCallout(s) {
    const m = metaFor(s.label);
    const mc = m.model && m.model !== '—' ? `m-${m.model}` : 'm-none';
    callout.innerHTML = `
      <div class="fco-top"><span class="fco-kind">agent</span><span class="fco-name">${m.agent}</span></div>
      <div class="fco-meta">
        <span class="fco-model ${mc}">${m.model}</span>
        <span class="fco-effort">effort · ${m.effort}</span>
        ${s.iter ? `<span class="fco-iter">${s.iter}</span>` : ''}
      </div>
      ${m.role ? `<div class="fco-role">${m.role}${s.tag ? ` — <em>${s.tag}</em>` : ''}</div>` : ''}`;
    callout.classList.add('show');
  }

  function go(c) {
    if (timer && c !== cur + 1) { /* manual jump keeps timer state */ }
    cur = Math.max(0, Math.min(steps.length, c));
    if (progress) progress.style.width = `${(cur / steps.length) * 100}%`;
    // collapse
    [...canvas.querySelectorAll('.flow-node')].forEach((n) => n.classList.remove('active', 'revealed', 'done', 'loop'));
    [...svg.querySelectorAll('.flow-edge.sub, .flow-edge.gan')].forEach((e) => e.classList.remove('lit', 'lit-fork'));

    if (cur === 0) {
      stage.dataset.tone = '';
      callout.classList.remove('show'); callout.innerHTML = '';
      moveToken(START_X - 88, ENTRY_Y, true);
      stage.scrollTo({ left: 0, behavior: 'auto' });
      if (narration) narration.innerHTML = `<b>${SCENARIOS[scenario].label} project.</b> ${SCENARIOS[scenario].blurb} <b>Step</b> through each agent, or <b>Play</b>.`;
      return;
    }
    const s = steps[cur - 1];
    const phases = SCENARIOS[scenario].phases;
    const entry = phaseEls[s.p.id];
    // prior phases: collapse their sub-tree, leave only a ✓ on the trunk pill
    for (let k = 0; k < s.pi; k++) phaseEls[phases[k].id].node.classList.add('done');
    // current phase
    entry.node.classList.add('active');
    stage.dataset.tone = entry.wide ? 'fork' : 'nest';
    // reveal agents reached so far in this phase
    const reached = steps.slice(0, cur).filter((st) => st.pi === s.pi && st.kind === 'agent').map((st) => st.id);
    [...new Set(reached)].forEach((id) => {
      const el = entry.sub[id]; if (!el) return;
      el.classList.add('revealed');
      const ed = entry.edgeByChild[id]; if (ed) ed.classList.add(entry.wide ? 'lit-fork' : 'lit');
    });
    if (s.p.flow === 'loop' && entry.loopEdge && reached.length >= 2) entry.loopEdge.classList.add('lit');

    if (narration) narration.innerHTML = s.p.say + (entry.wide && s.kind === 'agent' ? ' <span class="paren">— these run in parallel.</span>' : '');

    if (s.kind === 'phase') {
      moveToken(entry.px, TRUNK_Y);
      callout.classList.remove('show'); callout.innerHTML = '';
    } else {
      const el = entry.sub[s.id];
      el.classList.add('active');
      if (s.p.flow === 'loop') el.classList.add('loop');
      moveToken(xy(el).x, xy(el).y);
      setCallout(s);
    }
    // keep the current step in view
    const focusX = (s.kind === 'agent' && entry.sub[s.id]) ? xy(entry.sub[s.id]).x : entry.px;
    stage.scrollTo({ left: Math.max(0, focusX - stage.clientWidth / 2), behavior: 'smooth' });
  }

  function stop() { if (timer) { clearInterval(timer); timer = null; } if (playBtn) playBtn.textContent = cur >= steps.length ? '↺ Replay' : '▶ Play'; }
  function play() {
    if (cur >= steps.length) go(0);
    if (timer) { stop(); return; }
    if (playBtn) playBtn.textContent = '❚❚ Pause';
    timer = setInterval(() => { if (cur >= steps.length) { stop(); return; } go(cur + 1); }, 1700);
  }
  playBtn?.addEventListener('click', play);
  document.querySelector('#flow-step')?.addEventListener('click', () => { stop(); go(cur >= steps.length ? steps.length : cur + 1); });
  document.querySelector('#flow-reset')?.addEventListener('click', () => { stop(); go(0); });
  scWrap?.addEventListener('click', (e) => {
    const b = e.target.closest('.flow-sc'); if (!b) return;
    stop(); scenario = b.dataset.sc;
    scWrap.querySelectorAll('.flow-sc').forEach((x) => x.classList.toggle('active', x === b));
    if (playBtn) playBtn.textContent = '▶ Play';
    render();
  });

  render();
}

document.addEventListener('DOMContentLoaded', initFlow);
