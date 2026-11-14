// Public and synthetic design fixtures. No caller-controlled file paths are fetched.
const FILES = ['kvlcc2', 'kvlcc2-candidate-a', 'kvlcc2-candidate-b', 'kvlcc2-candidate-c', 'kvlcc2-candidate-d', 'kvlcc2-candidate-e'];

async function load(file) {
  const response = await fetch(`mock/files/designs/${file}.json`);
  if (!response.ok) throw new Error(`Design file unavailable: ${file}`);
  const record = await response.json();
  if (!record.design_id || record.engineering_approved !== false || !record.main_dimensions || !record.results) {
    throw new Error(`Invalid mock design: ${file}`);
  }
  return { record, updated_ms: Date.parse(response.headers.get('last-modified')) || null };
}

export async function listMockDesigns() {
  return Promise.all(FILES.map(async (file) => {
    try {
      const { record, updated_ms } = await load(file);
      return { id: record.design_id, name: record.name, status: record.status,
        main_dimensions: record.main_dimensions, ship_type: null, updated_ms, validation_error: null };
    } catch (error) {
      return { id: null, name: file, status: null, main_dimensions: {}, ship_type: null,
        updated_ms: null, validation_error: error.message };
    }
  }));
}

export async function openMockDesign(id) {
  for (const file of FILES) {
    try {
      const { record } = await load(file);
      if (record.design_id === id) return record;
    } catch { /* Invalid files remain visible in the list, but cannot open. */ }
  }
  throw new Error('Design not found or invalid.');
}

/* ---------- Decisions (sidecar file in the desktop app; memory here) ---------- */

const ACTIONS = ['accepted', 'deferred', 'rejected'];
const DISCIPLINES = ['basic_design', 'structure', 'machinery', 'outfitting', 'accommodation'];

// Synthetic history so the log is not empty in the mock. Names are role placeholders only.
const decisions = {
  'public-kvlcc2-example': [
    { candidate_id: 'synthetic-kvlcc2-candidate-c', action: 'rejected', discipline: 'basic_design',
      reason: 'Less cargo volume and more fuel per day than the parent.', designer_id: 'Basic design reviewer',
      recorded_at: '2026-11-13T02:10:00Z' },
    { candidate_id: 'synthetic-kvlcc2-candidate-a', action: 'deferred', discipline: 'basic_design',
      reason: 'Wait for the structure check of the longer hull.', designer_id: 'Basic design reviewer',
      recorded_at: '2026-11-13T02:30:00Z' },
    { candidate_id: 'synthetic-kvlcc2-candidate-d', action: 'deferred', discipline: 'structure',
      reason: 'Design draft is above the 21.0 m limit. Check the port limit first.', designer_id: 'Structure reviewer',
      recorded_at: '2026-11-13T06:45:00Z' },
  ].map((entry, index) => ({ id: `decision-mock-${index + 1}`, status: 'draft', ...entry })),
};

export async function listMockDecisions(projectId) {
  return structuredClone(decisions[projectId] || []);
}

/** Same checks as the desktop backend; the mock keeps decisions until the page reloads. */
export async function appendMockDecision(projectId, decision) {
  const reason = String(decision.reason || '').trim();
  const designer = String(decision.designer_id || '').trim();
  if (!ACTIONS.includes(decision.action)) throw new Error('The action must be accepted, deferred or rejected.');
  if (!DISCIPLINES.includes(decision.discipline)) throw new Error('The discipline is not known.');
  if (!reason) throw new Error('The reason is required.');
  if (!designer) throw new Error('The reviewer name is required.');
  await openMockDesign(projectId);
  const candidate = await openMockDesign(decision.candidate_id);
  if (candidate.lineage?.parent_design_id !== projectId) throw new Error('The candidate is not a design of this project.');
  const log = decisions[projectId] ||= [];
  const entry = { id: `decision-mock-${Date.now()}-${log.length + 1}`, candidate_id: decision.candidate_id,
    action: decision.action, discipline: decision.discipline, reason, designer_id: designer,
    recorded_at: new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'), status: 'draft' };
  log.push(entry);
  return structuredClone(entry);
}
