const fs = require('node:fs');
const path = require('node:path');
const { buildCourseId, buildSectionId, buildCourseExports, buildExportPayload } = require('./scheduling-data');
const { livePlannerPayload, catalogSnapshotPayload } = require('./planner-data');

const START_URL = 'https://globalsearch.cuny.edu/';
const log = (...args) => console.error(...args);
const DEFAULT_SEARCH = {
  institutionValue: 'HTR01', institutionLabel: 'Hunter College',
  termText: '2026 Fall Term', subjectText: 'Computer Science', subjectValue: 'CMSC',
  courseCareerText: 'Undergraduate', courseCareerValue: 'UGRD', headless: true,
  stdout: false, outputPath: undefined, browserChannel: '',
};

function readArgs(argv) {
  const search = { ...DEFAULT_SEARCH };
  const aliases = {
    cs: ['Computer Science', 'CMSC'], csci: ['Computer Science', 'CMSC'], cmsc: ['Computer Science', 'CMSC'],
    math: ['Mathematics', 'MATH'], stat: ['Statistics', 'STAT'],
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = () => {
      const value = argv[++index];
      if (!value || value.startsWith('--')) throw new Error(`Missing value for ${arg}`);
      return value;
    };
    if (arg === '--term') {
      const term = next();
      const match = term.match(/^(20\d{2})-(spring|summer|fall|winter)$/i);
      search.termText = match ? `${match[1]} ${match[2][0].toUpperCase()}${match[2].slice(1).toLowerCase()} Term` : term;
      search.termValue = /^\d+$/.test(term) ? term : undefined;
    } else if (arg === '--subject') {
      const subject = next();
      [search.subjectText, search.subjectValue] = aliases[subject.toLowerCase()] || [subject, ''];
    } else if (arg === '--subject-value') search.subjectValue = next();
    else if (arg === '--source') search.sourcePath = next();
    else if (arg === '--course-number') search.courseNumber = next();
    else if (arg === '--career') { search.courseCareerText = next(); search.courseCareerValue = ''; }
    else if (arg === '--career-value') search.courseCareerValue = next();
    else if (arg === '--all-careers') { search.courseCareerText = ''; search.courseCareerValue = ''; }
    else if (arg === '--institution') search.institutionValue = next();
    else if (arg === '--institution-label') search.institutionLabel = next();
    else if (arg === '--headed') search.headless = false;
    else if (arg === '--browser-channel') search.browserChannel = next();
    else if (arg === '--output') search.outputPath = next();
    else if (arg === '--stdout') search.stdout = true;
    else if (arg === '--no-file') { search.outputPath = ''; search.stdout = true; }
    else if (arg === '--open-only') throw new Error('ClassPath includes every offered section regardless of seats; --open-only is not supported');
    else if (arg === '--help') search.help = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }
  return search;
}

async function selectByText(page, selector, text, fallbackValue = '') {
  const options = await page.$$eval(`${selector} option`, opts => opts.map(option => ({
    value: option.value, text: option.textContent.trim().replace(/\s+/g, ' '),
  })));
  const normalizedText = text.toLowerCase();
  const option = options.find(item => item.value === text)
    || options.find(item => item.text.toLowerCase() === normalizedText)
    || options.find(item => item.text.toLowerCase().includes(normalizedText))
    || options.find(item => item.value === fallbackValue && fallbackValue);
  if (!option || !option.value) throw new Error(`Could not find option "${text}" in ${selector}`);
  await page.selectOption(selector, option.value);
  return option;
}

async function submitAndWait(page, buttonSelector) {
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'networkidle' }),
    page.locator(buttonSelector).click(),
  ]);
}

async function setCheckbox(page, selector, checked = true) {
  const changed = await page.locator(selector).evaluate((checkbox, nextChecked) => {
    checkbox.checked = nextChecked;
    checkbox.dispatchEvent(new Event('input', { bubbles: true }));
    checkbox.dispatchEvent(new Event('change', { bubbles: true }));
    return checkbox.checked;
  }, checked);
  if (changed !== checked) throw new Error(`Could not set checkbox ${selector}`);
}

async function chooseFirstPageCriteria(page, search) {
  await page.goto(START_URL, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('form[name="searchform"]');
  const term = await selectByText(page, '#t_pd', search.termText, search.termValue);
  search.selectedTermText = term.text;
  search.selectedTermValue = term.value;
  log(`Selected term: ${term.text} (${term.value})`);
  const institution = page.locator(`input[name="inst_selection"][value="${search.institutionValue}"]`);
  if (await institution.count()) await setCheckbox(page, `input[name="inst_selection"][value="${search.institutionValue}"]`);
  else await page.getByLabel(search.institutionLabel).check();
  await submitAndWait(page, 'input[name="next_btn"]');
}

async function chooseCriteriaPage(page, search) {
  await page.waitForSelector('form[name="class_search_form"]');
  const subject = await selectByText(page, '#subject_ld', search.subjectText, search.subjectValue);
  search.selectedSubjectText = subject.text;
  search.selectedSubjectValue = subject.value;
  if (search.courseCareerText || search.courseCareerValue) {
    await selectByText(page, '#courseCareerId', search.courseCareerText || search.courseCareerValue, search.courseCareerValue);
  }
  // Global Search defaults to open sections. Explicitly disable that filter.
  await setCheckbox(page, '#open_class_id', false);
  await submitAndWait(page, 'input[name="search_btn_search"]');
}

async function scrapeResults(page) {
  await page.waitForLoadState('domcontentloaded');
  return page.evaluate(() => {
    const clean = value => String(value || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
    const sections = new Map();
    for (const span of document.querySelectorAll('.testing_msg span')) {
      const match = clean(span.textContent).match(/\b([A-Z]{2,5})\s+([0-9]{3,5}[A-Z]?)\s*-\s*(.+)$/);
      if (!match) continue;
      const contentId = span.querySelector('a[href*="subjectToggle"]')?.getAttribute('href')?.match(/subjectToggle\('([^']+)'/)?.[1];
      const content = contentId ? document.getElementById(contentId) : span.closest('.testing_msg')?.nextElementSibling;
      let previous;
      for (const row of content?.querySelectorAll('table.classinfo tbody tr') || []) {
        const cell = label => row.querySelector(`td[data-label="${label}"]`)?.innerText.trim() || '';
        const classNumber = clean(cell('Class'));
        const meeting = { daysAndTimes: cell('DaysAndTimes'), meetingDates: clean(cell('Meeting Dates')) };
        if (!/^\d+$/.test(classNumber)) {
          if (previous && (meeting.daysAndTimes || meeting.meetingDates)) previous.meetings.push(meeting);
          continue;
        }
        const key = `${match[1]} ${match[2]}:${classNumber}`;
        if (!sections.has(key)) {
          const link = row.querySelector('td[data-label="Class"] a');
          sections.set(key, {
            subject: match[1], number: match[2], title: clean(match[3]), classNumber,
            section: clean(cell('Section')), instructionMode: clean(cell('Instruction Mode')),
            meetings: [], detailsUrl: link ? new URL(link.getAttribute('href'), document.baseURI).href : '',
          });
        }
        previous = sections.get(key);
        previous.meetings.push(meeting);
      }
    }
    return [...sections.values()];
  });
}

async function readDetailFields(page) {
  return page.evaluate(() => {
    const clean = value => String(value || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
    const lines = document.body.innerText.split(/\n+/).map(clean).filter(Boolean);
    const pick = label => {
      for (const row of document.querySelectorAll('table tr')) {
        const cells = [...row.querySelectorAll(':scope > th, :scope > td')];
        const index = cells.findIndex(cell => clean(cell.innerText).toLowerCase() === label.toLowerCase());
        if (index >= 0 && index < cells.length - 1) return clean(cells.slice(index + 1).map(cell => cell.innerText).join(' '));
      }
      const index = lines.findIndex(line => line.toLowerCase() === label.toLowerCase());
      return index >= 0 ? lines[index + 1] || '' : '';
    };
    const meetings = [];
    for (const table of document.querySelectorAll('table.classinfo')) {
      const headers = [...table.querySelectorAll('thead th')].map(h => clean(h.innerText).toLowerCase());
      for (const row of table.querySelectorAll('tbody tr')) {
        const cells = [...row.querySelectorAll(':scope > td')];
        if (!cells.length) continue;
        const timeIndex = headers.findIndex(h => /days.*times/.test(h));
        const dateIndex = headers.findIndex(h => /meeting dates/.test(h));
        const times = row.querySelector('td[data-label="DaysAndTimes"]') || cells[timeIndex >= 0 ? timeIndex : 0];
        const dates = row.querySelector('td[data-label="Meeting Dates"]') || cells[dateIndex >= 0 ? dateIndex : 3];
        meetings.push({ daysAndTimes: times?.innerText.trim() || '', meetingDates: clean(dates?.innerText) });
      }
    }
    return {
      classNumber: pick('Class Number'), session: pick('Session'), units: pick('Units'),
      instructionMode: pick('Instruction Mode'),
      requirementsText: pick('Enrollment Requirements'), meetings,
    };
  });
}

async function scrapeDetailPage(page, url) {
  await page.goto(url, { waitUntil: 'networkidle' });
  return readDetailFields(page);
}

async function enrichSectionsWithDetails(page, sections, search) {
  const enriched = [];
  for (const [index, section] of sections.entries()) {
    if (!section.detailsUrl) throw new Error(`Missing detail URL for class ${section.classNumber}; export was not written`);
    log(`Reading section ${index + 1}/${sections.length}: ${section.subject} ${section.number} ${section.section}`);
    const details = await scrapeDetailPage(page, section.detailsUrl);
    if (details.classNumber !== section.classNumber) throw new Error(`Detail page class number does not match ${section.classNumber}; export was not written`);
    if (/winter/i.test(details.session)) continue;
    if (!details.session || !details.units) throw new Error(`Incomplete detail page for ${section.classNumber}; export was not written`);
    const courseId = buildCourseId(search, section);
    enriched.push({
      ...section, ...details, courseId, sectionId: buildSectionId(search, section),
      instructionMode: details.instructionMode || section.instructionMode,
      meetings: details.meetings.length ? details.meetings : section.meetings,
    });
  }
  return enriched;
}

function defaultOutputPath(search, payload) {
  const subject = { CMSC: 'csci', MATH: 'math', STAT: 'stat' }[search.selectedSubjectValue]
    || (search.selectedSubjectValue || search.subjectText).toLowerCase().replace(/[^a-z0-9]+/g, '-');
  const suffix = search.courseNumber ? `-${search.courseNumber}` : '';
  const [year, season] = payload.term.split('-');
  return path.join(__dirname, '..', '..', 'course_data', `${subject}${suffix}-${season}-${year}.json`);
}

function writePayload(search, payload) {
  const json = `${JSON.stringify(payload, null, 2)}\n`;
  const outputPath = search.outputPath ?? defaultOutputPath(search, payload);
  if (outputPath) {
    fs.mkdirSync(path.dirname(outputPath), { recursive: true });
    fs.writeFileSync(`${outputPath}.tmp`, json);
    fs.renameSync(`${outputPath}.tmp`, outputPath);
    log(`Saved ${outputPath}: ${payload.courses.length} courses, ${payload.courses.reduce((n, c) => n + c.sections.length, 0)} sections`);
  }
  if (search.stdout) process.stdout.write(json);
  return payload;
}

async function main(argv = process.argv.slice(2)) {
  const search = readArgs(argv);
  if (search.help) {
    console.log(`Usage: node scripts/scraper/scrape.js [options]
  --term "2027 Spring Term"   Also accepts 2027-spring or source ID 1272
  --subject csci|math|stat    Or the full source subject name
  --course-number 13500      Optional single-course filter
  --output path.json         Default: course_data/<subject>-<season>-<year>.json
  --source snapshot.json     Reproduce saved catalog data offline instead of scraping
  --stdout                   Also print the JSON
  --no-file                  Print JSON without writing a file
  --headed                   Show the browser
  --browser-channel msedge   Use an installed browser instead of bundled Chromium
  --subject-value VALUE      Fallback source subject value
  --career TEXT              Default: Undergraduate
  --career-value VALUE       Fallback career value
  --all-careers              Include all careers
  --institution VALUE        Default: HTR01
  --institution-label TEXT   Default: Hunter College`);
    return;
  }
  if (search.sourcePath) {
    if (search.courseNumber) throw new Error('--course-number is not supported with --source');
    const subject = { CMSC: 'CSCI', MATH: 'MATH', STAT: 'STAT' }[search.subjectValue];
    if (!subject) throw new Error('Snapshot replay requires --subject csci|math|stat');
    search.selectedSubjectValue = search.subjectValue;
    return writePayload(search, catalogSnapshotPayload(JSON.parse(fs.readFileSync(search.sourcePath, 'utf8')), termNameForReplay(search), subject));
  }
  const { chromium } = require('playwright');
  const browser = await chromium.launch({ headless: search.headless, ...(search.browserChannel ? { channel: search.browserChannel } : {}) });
  try {
    const page = await browser.newPage();
    await chooseFirstPageCriteria(page, search);
    await chooseCriteriaPage(page, search);
    const resultSections = (await scrapeResults(page)).filter(s => !search.courseNumber || s.number === search.courseNumber);
    if (!resultSections.length) throw new Error('No sections matched; export was not written');
    const sections = await enrichSectionsWithDetails(page, resultSections, search);
    return writePayload(search, livePlannerPayload(search, sections));
  } finally { await browser.close(); }
}

if (require.main === module) main().catch(error => { console.error(error.message); process.exitCode = 1; });
module.exports = { readArgs, chooseFirstPageCriteria, chooseCriteriaPage, scrapeResults, readDetailFields,
  enrichSectionsWithDetails, buildCourseId, buildSectionId, buildCourseExports, buildExportPayload, defaultOutputPath, main };

function termNameForReplay(search) { return require('./scheduling-data').termName(search); }
