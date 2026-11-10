// ClassPath keeps academic dependencies but ignores section eligibility restrictions.
const cleanText = value => String(value ?? '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
const DAYS = { Mo: 'Mon', Tu: 'Tue', We: 'Wed', Th: 'Thu', Fr: 'Fri', Sa: 'Sat', Su: 'Sun' };
const REQUIREMENTS = ['prerequisites', 'corequisites', 'pre_or_corequisites'];

function dependencyText(value) {
  const text = cleanText(value && typeof value === 'object' ? value.text : value);
  // Remove separate eligibility sentences; retain the prerequisite wording and its AND/OR structure.
  return text.split(/(?<=[.!?])\s+/).filter(sentence =>
    !/^(?:only\s+open\s+to|open\s+only\s+to|restricted\s+to|(?:only\s+)?(?:for\s+)?(?:the\s+)?(?:daedalus\s+)?honors?\s+(?:cohort|students)|(?:department(?:al)?|instructor)\s+(?:permission|consent)|(?:math|reading|writing)(?:[,\s]+(?:math|reading|writing|and))*\s+proficient)\b/i.test(sentence)
  ).join(' ').trim() || null;
}

function getRequirements(value) {
  const text = cleanText(value);
  const labels = [...text.matchAll(/\b(Prerequisites?\s+or\s+Co-?requisites?|Pre[\s/-]*(?:or[\s/-]*)?Co-?requisites?|Co-?requisites?|Prerequisites?)\s*:/gi)];
  const result = Object.fromEntries(REQUIREMENTS.map(key => [key, null]));
  labels.forEach((match, index) => {
    const label = match[1].toLowerCase();
    const key = label.startsWith('pre') && /co-?requisite/.test(label)
      ? 'pre_or_corequisites' : label.startsWith('co') ? 'corequisites' : 'prerequisites';
    const part = dependencyText(text.slice(match.index + match[0].length, labels[index + 1]?.index ?? text.length));
    if (part) result[key] = [result[key], part].filter(Boolean).join('; ');
  });
  return result;
}

function parseCredits(value) {
  const text = cleanText(value);
  if (!/^\d+(?:\.\d+)?(?:\s*(?:-|to)\s*\d+(?:\.\d+)?)?\s*(?:units?|credits?)?$/i.test(text)) return null;
  const numbers = text.match(/\d+(?:\.\d+)?/g).map(Number);
  if (numbers.length === 1 || numbers[0] === numbers[1]) return numbers[0];
  return numbers[0] <= numbers[1] ? { minimum: numbers[0], maximum: numbers[1] } : null;
}

function parseTime(value) {
  const match = cleanText(value).match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i);
  if (!match) return null;
  let hour = Number(match[1]);
  const minute = Number(match[2]);
  if (hour < 1 || hour > 12 || minute > 59) return null;
  hour = hour % 12 + (match[3].toUpperCase() === 'PM' ? 12 : 0);
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
}

function parseDateRange(value) {
  const dates = [...cleanText(value).matchAll(/\b(\d{1,2})\/(\d{1,2})\/(\d{4})\b/g)].map(([, m, d, y]) => {
    const iso = `${y}-${m.padStart(2, '0')}-${d.padStart(2, '0')}`;
    const date = new Date(`${iso}T00:00:00Z`);
    return !Number.isNaN(date.valueOf()) && date.toISOString().slice(0, 10) === iso ? iso : null;
  });
  return { start_date: dates[0] ?? null, end_date: dates[1] ?? null };
}

function parseMeetings(rows, instructionMode = '') {
  const meetings = [];
  for (const row of rows.length ? rows : [{}]) {
    const parts = String(row.daysAndTimes || '').split(/\n+|;/).map(cleanText).filter(Boolean);
    for (const raw of parts.length ? parts : ['']) {
      const match = raw.match(/^((?:(?:Mo|Tu|We|Th|Fr|Sa|Su)\s*)+)\s*(\d{1,2}:\d{2}\s*(?:AM|PM))\s*-\s*(\d{1,2}:\d{2}\s*(?:AM|PM))$/i);
      const dayTokens = match?.[1].match(/Mo|Tu|We|Th|Fr|Sa|Su/gi) || [];
      const days = [...new Set(dayTokens.map(d => DAYS[d[0].toUpperCase() + d[1].toLowerCase()]))];
      const start = match ? parseTime(match[2]) : null;
      const end = match ? parseTime(match[3]) : null;
      const scheduled = days.length > 0 && start && end && start !== end;
      const blank = !raw || /^(?:TBA|TBD|To Be Announced|Asynchronous)$/i.test(raw);
      const asynchronous = blank && /\basynchronous\b/i.test(instructionMode);
      meetings.push({
        days: scheduled ? days : [], start: scheduled ? start : null, end: scheduled ? end : null,
        schedule_type: scheduled ? 'scheduled' : asynchronous ? 'asynchronous' : 'unknown',
        ...parseDateRange(row.meetingDates),
        end_day_offset: scheduled && end < start ? 1 : 0,
      });
    }
  }
  return [...new Map(meetings.map(m => [JSON.stringify(m), m])).values()];
}

function buildSectionId(search, section) {
  const term = search.selectedTermValue || search.termValue;
  if (!term || !/^\d+$/.test(section.classNumber)) throw new Error('A source term and class number are required for section identity');
  return `${search.institutionValue}-${term}-${section.classNumber}`;
}

const buildCourseId = (_search, section) => `${section.subject} ${section.number}`;

function termName(search) {
  const text = search.selectedTermText || search.termText;
  const match = text.match(/\b(20\d{2})\s+(Spring|Summer|Fall|Winter)\s+Term\b/i);
  if (!match) throw new Error(`Cannot determine academic term from "${text}"`);
  return `${match[1]}-${match[2].toLowerCase()}`;
}

function projectSection(raw) {
  return {
    id: raw.sectionId,
    section: cleanText(raw.section).split(/\s+/)[0],
    ...getRequirements(raw.requirementsText),
    meetings: parseMeetings(raw.meetings, raw.instructionMode),
  };
}

function buildCourseExports(sections) {
  const courses = new Map();
  for (const raw of sections) {
    if (/winter/i.test(raw.session || '')) continue;
    if (!courses.has(raw.courseId)) courses.set(raw.courseId, { course_id: raw.courseId, title: raw.title, creditValues: [], sections: [] });
    const course = courses.get(raw.courseId);
    if (course.title !== raw.title) throw new Error(`Conflicting titles for ${raw.courseId}`);
    if (course.sections.some(s => s.id === raw.sectionId)) throw new Error(`Duplicate section ${raw.sectionId}`);
    course.creditValues.push(parseCredits(raw.units));
    course.sections.push(projectSection(raw));
  }
  return compactCourses([...courses.values()].sort((a, b) => a.course_id.localeCompare(b.course_id)).map(course => {
    const credits = [...new Set(course.creditValues.map(value => JSON.stringify(value)))];
    return {
      course_id: course.course_id, title: course.title,
      credits: credits.length === 1 ? course.creditValues[0] : null,
      sections: course.sections.sort((a, b) => a.id.localeCompare(b.id)),
    };
  }));
}

// Also accepts the previous export, so cached source data can be compacted without another scrape.
function compactCourses(courses) {
  return courses.map(course => {
    const sections = course.sections.map(section => ({
      id: section.id, section: section.section,
      ...Object.fromEntries(REQUIREMENTS.map(key => [key, dependencyText(
        Object.hasOwn(section, key) ? section[key] : course[key]
      )])),
      meetings: section.meetings.map(meeting => ({
        days: meeting.days, start: meeting.start, end: meeting.end,
        schedule_type: meeting.schedule_type || section.schedule_type || 'unknown',
        start_date: meeting.start_date ?? null, end_date: meeting.end_date ?? null,
        end_day_offset: meeting.end_day_offset ?? 0,
      })),
    }));
    const result = { course_id: course.course_id, title: course.title, credits: course.credits };
    for (const key of REQUIREMENTS) {
      const values = [...new Set(sections.map(section => section[key]))];
      result[key] = values.length === 1 ? values[0] : null;
      if (values.length === 1) sections.forEach(section => { delete section[key]; });
    }
    return { ...result, sections };
  });
}

function buildExportPayload(search, courses) {
  if (!courses.length) throw new Error('No regular-session courses matched; export was not written');
  return {
    term: termName(search),
    timezone: 'America/New_York',
    courses,
  };
}

module.exports = { cleanText, dependencyText, getRequirements, parseCredits, parseTime, parseDateRange, parseMeetings,
  buildSectionId, buildCourseId, termName, projectSection, buildCourseExports, compactCourses, buildExportPayload };
