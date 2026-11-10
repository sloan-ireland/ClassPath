// Offline only: course_data/*.json -> SQL for the archived ClassPath schema.
// Never connects to Supabase or applies SQL. Run: npm run prepare:sql
// Optional: --input-dir path --output-dir path
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');
const fields = ['prerequisites', 'corequisites', 'pre_or_corequisites'];
const sourceTerms = { '2026-fall': '1269', '2027-spring': '1272' };
const dayNames = new Set(['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']);
const quote = v => v === null ? 'null' : typeof v === 'number' ? String(v) : "'" + String(v).replaceAll("'", "''") + "'";

function ruleText(value) {
  if (value == null) return null;
  if (typeof value === 'string') return value;
  assert.ok(typeof value === 'object' && !Array.isArray(value), 'Malformed academic rule');
  // Preserve both the structured tree and source text in the existing TEXT
  // column. Consumers may JSON.parse it; no boolean/grade evidence is discarded.
  return JSON.stringify(value);
}

function flatten(data, filename, seen = new Set()) {
  assert.match(data.term, /^20\d{2}-(spring|summer|fall|winter)$/);
  assert.equal(data.timezone, 'America/New_York');
  assert.ok(Array.isArray(data.courses) && data.courses.length, `Empty or malformed ${filename}`);
  const sourceTerm = sourceTerms[data.term];
  assert.ok(sourceTerm, `Unmapped CUNY source term ${data.term}; add a verified source ID before importing`);
  const rows = { terms: [[data.term, data.timezone]], courses: [], sections: [], meetings: [] };
  const courses = new Set();
  for (const course of data.courses) {
    assert.equal(course.term, data.term);
    assert.match(course.course_id, /^[A-Z]+ \d{3,5}[A-Z]*$/);
    assert.ok(!courses.has(course.course_id), 'Duplicate course'); courses.add(course.course_id);
    const credits = course.credits;
    const minimum = credits === null ? null : typeof credits === 'number' ? credits : credits?.min;
    const maximum = credits === null ? null : typeof credits === 'number' ? credits : credits?.max;
    assert.ok(minimum === null && maximum === null || Number.isFinite(minimum) && minimum >= 0 && Number.isFinite(maximum) && maximum >= minimum, 'Invalid credits');
    // Planner JSON omits titles. Use the course code only for NEW rows; the
    // upsert below deliberately preserves titles already in the database.
    rows.courses.push([data.term, course.course_id, course.title || course.course_id,
      minimum, maximum, ...fields.map(k => ruleText(course[k]))]);
    assert.ok(Array.isArray(course.required_components) && course.required_components.length);
    assert.ok(Array.isArray(course.sections) && course.sections.length);
    for (const section of course.sections) {
      assert.match(String(section.id), /^\d+$/, 'Expected a CUNY class number');
      assert.ok(course.required_components.includes(section.type), 'Section component not declared by course');
      const id = `HTR01-${sourceTerm}-${section.id}`;
      assert.ok(!seen.has(id), `Duplicate section ${id}`); seen.add(id);
      const overrides = {};
      if (section.academic_rules != null) assert.ok(typeof section.academic_rules === 'object' && !Array.isArray(section.academic_rules));
      for (const key of fields) {
        if (Object.hasOwn(section.academic_rules || {}, key)) overrides[key] = ruleText(section.academic_rules[key]);
        else if (Object.hasOwn(section, key)) overrides[key] = ruleText(section[key]);
      }
      const unknownOverrides = Object.keys(section.academic_rules || {}).filter(k => !fields.includes(k));
      assert.equal(unknownOverrides.length, 0, 'Unsupported section academic override');
      rows.sections.push([id, data.term, course.course_id, `${section.id}-${section.type}`, JSON.stringify(overrides)]);
      assert.ok(Array.isArray(section.meetings), 'Malformed meetings');
      const meetings = section.meetings.length ? section.meetings : [{ days: [], start: null, end: null }];
      meetings.forEach((meeting, index) => {
        const state = meeting.schedule_type || section.schedule_type;
        assert.ok(['scheduled', 'asynchronous', 'unknown'].includes(state), `Unresolved meeting state ${state}`);
        assert.ok(Array.isArray(meeting.days) && meeting.days.every(d => dayNames.has(d)) && new Set(meeting.days).size === meeting.days.length);
        for (const time of [meeting.start, meeting.end]) assert.ok(time === null || typeof time === 'string' && /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(time));
        if (state === 'scheduled') assert.ok(meeting.days.length && meeting.start && meeting.end && meeting.start < meeting.end, 'Invalid or unsupported overnight meeting');
        else assert.ok(!meeting.days.length && meeting.start === null && meeting.end === null, 'Non-timed state has timed data');
        // Planner format intentionally omits dates; do not invent date bounds.
        rows.meetings.push([id, index, meeting.days, meeting.start, meeting.end, state, null, null, 0]);
      });
    }
  }
  return rows;
}

function upsert(table, columns, keys, rows, omitUpdates = [], render = quote) {
  if (!rows.length) return '';
  const values = rows.map(row => '(' + row.map((v, i) => render(v, i)).join(',') + ')').join(',\n');
  const updates = columns.filter(c => !keys.includes(c) && !omitUpdates.includes(c)).map(c => {
    if (c === 'start_date' || c === 'end_date') return `${c}=coalesce(excluded.${c},public.${table}.${c})`;
    return `${c}=excluded.${c}`;
  }).join(',');
  return `insert into public.${table} (${columns.join(',')}) values\n${values}\non conflict (${keys.join(',')}) do update set ${updates};\n`;
}

function renderImport(rows) {
  return '-- ClassPath only: kxjppqyawhfjclbidtwc. Review before applying.\n'
    + '-- Existing titles/section labels/dates are preserved. New missing titles use course codes.\n'
    + '-- Academic objects are JSON-serialized into TEXT; planner-specific metadata stays in source JSON.\n'
    + 'begin;\n'
    + upsert('terms', ['term_id', 'timezone'], ['term_id'], rows.terms)
    + upsert('courses', ['term_id', 'course_id', 'title', 'credits_min', 'credits_max', ...fields], ['term_id', 'course_id'], rows.courses, ['title'])
    + upsert('sections', ['section_id', 'term_id', 'course_id', 'section_name', 'dependency_overrides'], ['section_id'], rows.sections, ['section_name'],
      (v, i) => i === 4 ? `${quote(v)}::jsonb` : quote(v))
    + upsert('meetings', ['section_id', 'meeting_index', 'days', 'start_time', 'end_time', 'schedule_type', 'start_date', 'end_date', 'end_day_offset'], ['section_id', 'meeting_index'], rows.meetings, [],
      (v, i) => i === 2 ? v.length ? `array[${v.map(quote).join(',')}]::text[]` : 'array[]::text[]' : quote(v))
    + 'commit;\n';
}

function prepare(inputDir = path.join(root, 'course_data'), outputDir = path.join(root, 'supabase', 'import')) {
  const seen = new Set();
  const entries = [];
  for (const subject of ['csci', 'math', 'stat']) for (const season of ['fall-2026', 'spring-2027']) {
    const file = `${subject}-${season}.json`;
    const raw = fs.readFileSync(path.join(inputDir, file), 'utf8');
    const rows = flatten(JSON.parse(raw), file, seen);
    entries.push({ file, rows, sha256: crypto.createHash('sha256').update(raw).digest('hex') });
  }
  // Validate the complete batch before writing files. Never applies SQL.
  fs.mkdirSync(outputDir, { recursive: true });
  const manifest = { project_id: 'kxjppqyawhfjclbidtwc', files: [], counts: { course_offerings: 0, sections: 0, meetings: 0 },
    limitations: ['Planner JSON omits titles, section labels, dates, and registration links.', 'Existing titles/labels/dates are preserved on conflict; new titles use course IDs.', 'Prerequisite objects remain JSON-serialized text; database consumers must handle that representation.', 'No stale rows are deleted; this is an upsert import.'] };
  for (const entry of entries) {
    const sqlName = entry.file.replace(/\.json$/, '.sql');
    fs.writeFileSync(path.join(outputDir, sqlName), renderImport(entry.rows));
    const counts = { course_offerings: entry.rows.courses.length, sections: entry.rows.sections.length, meetings: entry.rows.meetings.length };
    manifest.files.push({ source: entry.file, sql: sqlName, sha256: entry.sha256, ...counts });
    for (const key of Object.keys(counts)) manifest.counts[key] += counts[key];
  }
  fs.writeFileSync(path.join(outputDir, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
  return manifest;
}

if (require.main === module) {
  let input, output;
  for (let i = 2; i < process.argv.length; i++) {
    const option = process.argv[i];
    if (!['--input-dir', '--output-dir'].includes(option) || !process.argv[i + 1]) throw new Error('Usage: node scripts/prepare-supabase.cjs [--input-dir path] [--output-dir path]');
    const value = path.resolve(process.argv[++i]);
    if (option === '--input-dir') input = value; else output = value;
  }
  console.log(JSON.stringify(prepare(input, output), null, 2));
}
module.exports = { flatten, renderImport, prepare, ruleText };
