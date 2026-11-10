// Shared projection for live Playwright sections and saved catalog snapshots.
// Output contract: the six JSON datasets on ClassPath main.
const { cleanText, getRequirements, parseCredits, parseMeetings, termName } = require('./scheduling-data');
const COMPONENTS = { LEC: 'lecture', REC: 'recitation', LAB: 'laboratory', DIS: 'discussion',
  SEM: 'seminar', IND: 'independent study', INT: 'internship', RSC: 'research', CLN: 'clinical',
  FLD: 'fieldwork', STU: 'studio', PRC: 'practicum', TUT: 'tutorial', WKS: 'workshop' };
const FIELDS = ['prerequisites', 'corequisites', 'pre_or_corequisites'];

function assumptions(subject, term) {
  const season = term.split('-')[1];
  // Preserve the existing main-branch files, including their Spring capitalization.
  const session = season === 'spring' ? 'Spring' : season;
  return [
    'Choose one section of each required component. Specific registration pairings and cohort restrictions are intentionally ignored for this experiment.',
    'Credits count once per course, not once per selected component.',
    'Prerequisite all/any expressions preserve existing structured parser output. Text preserves original wording, including grades and other conditions; text-only requirements still need interpretation.',
    `Null requirements mean unavailable or unconfirmed, not confirmed absence. Referenced prerequisite courses may be outside this ${subject}-only export.`,
    'Unknown meeting times are not asynchronous or conflict-free.',
    `Winter-session sections are excluded. Date ranges and locations are omitted; weekly conflict checking assumes overlapping dates within the regular ${session} session.`,
  ];
}

function prerequisite(text, logic) {
  if (logic) {
    const children = [...(logic.required_courses || []), ...(logic.one_of_groups || []).map(any => ({ any }))];
    if (children.length) return { all: children, ...(text ? { text } : {}) };
  }
  // A fresh scrape has no reviewed catalog parser output. Preserve its text and
  // mark it unstructured rather than silently inventing an AND/OR interpretation.
  return text ? { text } : null;
}

function liveRule(text) {
  if (!text) return null;
  // Parse only complete, unambiguous course expressions. Keep the original text
  // (including grades) for downstream evidence checks. Unsupported conditions,
  // omitted subjects, and mixed unparenthesized AND/OR remain text-only.
  const expression = text.replace(/[,\s]*(?:all\s+|both\s+)?with\s+(?:a\s+)?(?:grade\s+of\s+)?[ABCDF][+-]?\s+or\s+(?:better|higher)\.?\s*$/i, '')
    .replace(/[.\s]+$/, '').trim();
  const tokens = expression.match(/[A-Z]{2,}\s+\d{3,5}[A-Z]*|\bAND\b|\bOR\b|[()]/gi) || [];
  const residue = expression.replace(/[A-Z]{2,}\s+\d{3,5}[A-Z]*|\bAND\b|\bOR\b|[()]/gi, '').trim();
  if (residue || !tokens.length) return { text };
  let index = 0;
  const course = token => {
    const match = token.match(/^([A-Z]{2,})\s+(\d{3,5}[A-Z]*)$/i);
    if (!match) throw new Error('not a course');
    let number = match[2].toUpperCase();
    if (/^\d{3}$/.test(number)) number += '00';
    return `${match[1].toUpperCase()} ${number}`;
  };
  function atom() {
    if (tokens[index] === '(') {
      index++;
      const node = group();
      if (tokens[index++] !== ')') throw new Error('unclosed group');
      return node;
    }
    return course(tokens[index++] || '');
  }
  function group() {
    const children = [atom()];
    let operator;
    while (index < tokens.length && tokens[index] !== ')') {
      const next = tokens[index++].toLowerCase();
      if (!['and', 'or'].includes(next) || (operator && operator !== next)) throw new Error('ambiguous expression');
      operator = next;
      children.push(atom());
    }
    return operator ? { [operator === 'and' ? 'all' : 'any']: children } : children[0];
  }
  try {
    const tree = group();
    if (index !== tokens.length) return { text };
    return tree && typeof tree === 'object' && tree.all ? { ...tree, text } : { all: [tree], text };
  } catch { return { text }; }
}

function payload(term, subject, courses) {
  if (!courses.length) throw new Error('No regular-session courses matched; export was not written');
  return { term, timezone: 'America/New_York', assumptions: assumptions(subject, term), courses };
}

function catalogSnapshotPayload(source, term, subject) {
  const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  if (!Array.isArray(source.courses) || !Array.isArray(source.sections) || !Array.isArray(source.rules)) {
    throw new Error('Source must be a saved catalog snapshot with courses, sections and rules');
  }
  const courses = source.courses.map(course => {
    if (!course.course_id.startsWith(subject + ' ')) throw new Error('Source subject does not match --subject');
    const sections = source.sections.filter(s => s.offering_id === course.offering_id && !/winter/i.test(s.session || ''));
    const logic = source.rules.find(r => r.course_version_id === course.version_id && r.kind === 'prerequisite')?.source_logic;
    const text = course.prerequisites || (/prereq/i.test(course.enrollment_requirements || '') ? course.enrollment_requirements : null);
    return {
      term, course_id: course.course_id,
      credits: course.min_credits === course.max_credits ? course.min_credits : { min: course.min_credits, max: course.max_credits },
      prerequisites: prerequisite(text, logic), corequisites: course.corequisites ? { text: course.corequisites } : null,
      ...(course.pre_or_corequisites ? { pre_or_corequisites: { text: course.pre_or_corequisites } } : {}),
      required_components: [...new Set(sections.map(s => String(s.component || 'unknown').trim().toLowerCase().replace(/[^a-z0-9]+/g, '_')))],
      sections: sections.sort((a, b) => String(a.id).localeCompare(String(b.id))).map(s => {
        const states = [...new Set((s.meetings || []).map(m => m.state))];
        const meetings = (s.meetings || []).map(m => ({ days: m.days.map(n => days[n - 1]),
          start: m.start?.slice(0, 5) ?? null, end: m.end?.slice(0, 5) ?? null,
          ...(states.length > 1 ? { schedule_type: m.state } : {}) }));
        return { id: String(s.id), type: String(s.component || 'unknown').trim().toLowerCase().replace(/[^a-z0-9]+/g, '_'),
          session: s.session, schedule_type: states.length === 1 ? states[0] : states.length ? 'mixed' : 'unknown',
          meetings: [...new Map(meetings.map(m => [JSON.stringify(m), m])).values()] };
      }),
    };
  }).filter(c => c.sections.length).sort((a, b) => a.course_id.localeCompare(b.course_id));
  const ids = courses.flatMap(c => c.sections.map(s => s.id));
  if (new Set(ids).size !== ids.length) throw new Error('Duplicate section identity in snapshot');
  return payload(term, subject, courses);
}

function livePlannerPayload(search, rawSections) {
  const term = termName(search);
  const groups = new Map();
  for (const raw of rawSections) {
    if (/winter/i.test(raw.session || '')) continue;
    const match = cleanText(raw.section).match(/-([A-Z]+)\b/i);
    const type = COMPONENTS[match?.[1]?.toUpperCase()];
    if (!type) throw new Error(`Unknown component for ${raw.courseId} section ${raw.section}; export was not written`);
    const credits = parseCredits(raw.units);
    const dependencies = getRequirements(raw.requirementsText);
    const meetings = parseMeetings(raw.meetings, raw.instructionMode);
    // The target weekly-only format cannot safely express overnight meetings.
    if (meetings.some(m => m.end_day_offset)) throw new Error('Overnight meeting cannot be represented in the target course_data format');
    const states = [...new Set(meetings.map(m => m.schedule_type))];
    const projected = meetings.map(m => ({ days: m.days, start: m.start, end: m.end,
      ...(states.length > 1 ? { schedule_type: m.schedule_type } : {}) }));
    const section = { id: String(raw.classNumber), type, session: raw.session,
      schedule_type: states.length === 1 ? states[0] : states.length ? 'mixed' : 'unknown',
      meetings: [...new Map(projected.map(m => [JSON.stringify(m), m])).values()] };
    if (!groups.has(raw.courseId)) groups.set(raw.courseId, { credits, dependencies, sections: [] });
    const group = groups.get(raw.courseId);
    if (JSON.stringify(group.credits) !== JSON.stringify(credits)) throw new Error(`Conflicting credits for ${raw.courseId}`);
    if (group.sections.some(s => s.id === section.id)) throw new Error(`Duplicate section ${section.id}`);
    const overrides = {};
    for (const field of FIELDS) if (group.dependencies[field] !== dependencies[field]) {
      // Preserve section-specific conditions in the optional override supported
      // by the independent validator; the course field alone is not sufficient.
      for (const prior of group.sections) {
        prior.academic_rules ||= {};
        if (!(field in prior.academic_rules)) prior.academic_rules[field] = liveRule(group.dependencies[field]);
      }
      overrides[field] = liveRule(dependencies[field]);
    }
    if (Object.keys(overrides).length) section.academic_rules = overrides;
    group.sections.push(section);
  }
  const subject = [...groups.keys()][0]?.split(' ')[0];
  const courses = [...groups].sort(([a], [b]) => a.localeCompare(b)).map(([course_id, g]) => ({
    term, course_id, credits: g.credits && typeof g.credits === 'object' ? { min: g.credits.minimum, max: g.credits.maximum } : g.credits,
    prerequisites: liveRule(g.dependencies.prerequisites), corequisites: liveRule(g.dependencies.corequisites),
    ...(g.dependencies.pre_or_corequisites ? { pre_or_corequisites: liveRule(g.dependencies.pre_or_corequisites) } : {}),
    required_components: [...new Set(g.sections.map(s => s.type))],
    sections: g.sections.sort((a, b) => a.id.localeCompare(b.id)),
  }));
  return payload(term, subject, courses);
}

module.exports = { livePlannerPayload, catalogSnapshotPayload, liveRule };
