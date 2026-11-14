// Public and synthetic design fixtures. No caller-controlled file paths are fetched.
const FILES = ['kvlcc2', 'kvlcc2-cb-variant'];

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
