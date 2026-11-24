import glob
import heapq
import itertools
import json
import re
from dataclasses import dataclass, field

DAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ---------------------------------------------------------------------------
# 1. Loading data

def normalize_course_id(raw):
    """Turn messy IDs into one standardized form.
    'Csci 235' -> 'CSCI 23500', 'CSCI-26000' -> 'CSCI 26000', 'MATH 155' -> 'MATH 15500'
    """
    m = re.match(r"\s*([A-Za-z]+)[\s-]*(\d+)([A-Za-z]*)\s*$", raw)
    if not m:
        return raw.strip().upper()
    subject, number, suffix = m.group(1).upper(), m.group(2), m.group(3).upper()
    if len(number) == 3 and not suffix:   # Hunter short form: 235 means 23500
        number += "00"
    return f"{subject} {number}{suffix}"


def load_courses(term, data_dir="course_data"):
    """Load every course file for one term (e.g. '2026-fall') into a dict
    {course_id: course_record}. Merges CSCI, MATH and STAT files."""
    courses = {}
    for path in sorted(glob.glob(f"{data_dir}/*.json")):
        with open(path) as f:
            data = json.load(f)
        if data["term"] != term:
            continue
        for course in data["courses"]:
            courses[normalize_course_id(course["course_id"])] = course
    return courses


# ---------------------------------------------------------------------------
# 2. Time helpers + the "no overlap" constraint

#convert to minutes
def to_minutes(hhmm):
    """'14:30' -> 870 (minutes after midnight). Easier to compare than strings."""
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def section_blocks(section):
    """Flatten a section into simple time blocks: [(day, start_min, end_min), ...].
    One meeting like {days: [Mon, Wed], 13:00-14:15} becomes two blocks."""
    blocks = []
    for meeting in section["meetings"]:
        if meeting["start"] is None:
            continue
        for day in meeting["days"]:
            blocks.append((day, to_minutes(meeting["start"]), to_minutes(meeting["end"])))
    return blocks


def blocks_overlap(blocks_a, blocks_b):
    """Two classes clash if they are on the same day AND their times overlap.
    Times overlap when one starts before the other ends (and vice versa).
    Back-to-back (one ends 14:15, next starts 14:15) is NOT a clash."""
    for day_a, start_a, end_a in blocks_a:
        for day_b, start_b, end_b in blocks_b:
            if day_a == day_b and start_a < end_b and start_b < end_a:
                return True
    return False


# ---------------------------------------------------------------------------
# 3. Prerequisites

def check_prereq(expr, completed):
    """Check a structured prereq tree against the student's completed courses.

    expr can be:
      'CSCI 12700'                  -> done if the student took it
      {'all': [...]}                -> every item must be satisfied (AND)
      {'any': [...]}                -> at least one item must be satisfied (OR)
    Items inside can themselves be nested trees, so we call ourselves (recursion).
    """
    if isinstance(expr, str):
        return normalize_course_id(expr) in completed
    # all = you need every item
    if "all" in expr:
        return all(check_prereq(item, completed) for item in expr["all"])
    # any = you need at least one item
    if "any" in expr:
        return any(check_prereq(item, completed) for item in expr["any"])
    return True


def eligibility(course, completed):
    """Return (status, message) where status is one of:
       'ok'       -> structured prereqs, all satisfied
       'blocked'  -> structured prereqs, NOT satisfied
       'unknown'  -> we can't verify (null prereqs, or text-only that the LLM
                     step hasn't parsed yet). We allow it but attach a warning.
    """
    prereq = course.get("prerequisites")
    if prereq is None:
        return "unknown", "prerequisites not confirmed in data"
    if "all" not in prereq and "any" not in prereq:
        return "unknown", f"text-only prereq needs parsing: {prereq.get('text', '')[:80]}"
    if check_prereq(prereq, completed):
        return "ok", ""
    shown = prereq.get("text") or json.dumps({k: v for k, v in prereq.items() if k != "text"})
    return "blocked", f"missing prereqs: {shown[:80]}"


# ---------------------------------------------------------------------------
# 4. Domains: every valid way to take one course

@dataclass
class Option:
    """One way to take a course: a specific lecture (+ recitation, if required)."""
    course_id: str
    sections: tuple          # the chosen section dicts
    blocks: list             # all their time blocks combined
    credits: int
    warnings: list = field(default_factory=list)
    alternatives: list = field(default_factory=list)  # other section combos, same times


SKIP = None  # used as the "don't take this optional course" value


def build_domain(course_id, course, allow_unknown_times=False):
    """List every Option for a course.

    Rule from the dataset: pick ONE section of EACH required component.
    So for ['lecture', 'recitation'] we take every (lecture, recitation) pair.

    Unknown meeting times are NOT 'free' (dataset assumption). By default we drop
    those sections. Asynchronous (online, no set time) sections are fine.
    """
    per_component = []
    for component in course["required_components"]:
        choices = []
        for sec in course["sections"]:
            if sec["type"] != component:
                continue
            if sec["schedule_type"] == "unknown" and not allow_unknown_times:
                continue
            choices.append(sec)
        per_component.append(choices)

    options = []
    # itertools.product = every combination, one pick from each list
    for combo in itertools.product(*per_component):
        blocks = []
        warnings = []
        for sec in combo:
            blocks.extend(section_blocks(sec))
            if sec["schedule_type"] == "unknown":
                warnings.append(f"{course_id} section {sec['id']} has unknown meeting time")
        # a lecture+recitation pair that clashes with ITSELF is not valid
        if len(combo) > 1 and any(
            blocks_overlap(section_blocks(a), section_blocks(b))
            for a, b in itertools.combinations(combo, 2)
        ):
            continue
        options.append(Option(course_id, combo, blocks, course["credits"], warnings))
    return merge_identical_times(options)


def merge_identical_times(options):
    """Many sections meet at EXACTLY the same times (MATH 12550 has 60 sections).
    For conflicts and scoring they are interchangeable, so we keep one option per
    time pattern and remember the others as 'alternatives'. This shrinks the search
    a lot and stops the top 3 from being the same schedule with different
    section numbers."""
    groups = {}
    for opt in options:
        key = tuple(sorted(opt.blocks)) + tuple(s["schedule_type"] for s in opt.sections)
        if key in groups:
            groups[key].alternatives.append(opt.sections)
        else:
            groups[key] = opt
    return list(groups.values())


# ---------------------------------------------------------------------------
# 5. The heuristic: how "nice" is a schedule? (lower penalty = better)

DEFAULT_PREFS = {
    "earliest_start": "10:00",   # classes before this get penalized
    "latest_end": "18:00",       # classes after this get penalized
    "day_weight": 3.0,           # penalty per day you have to come to campus
    "gap_weight": 1.0,           # penalty per hour of waiting between classes
    "early_late_weight": 2.0,    # penalty per class block outside your window
    "avoid_days": [],            # e.g. ["Fri"] -> big penalty for Friday classes
    "avoid_day_weight": 10.0,
    "unknown_weight": 5.0,       # penalty per warning (unverified prereq, etc.)
}


def score_schedule(options, prefs):
    blocks = [b for opt in options for b in opt.blocks]
    early, late = to_minutes(prefs["earliest_start"]), to_minutes(prefs["latest_end"])
    penalty = 0.0

    by_day = {}
    for day, start, end in blocks:
        by_day.setdefault(day, []).append((start, end))
        if start < early or end > late:
            penalty += prefs["early_late_weight"]
        if day in prefs["avoid_days"]:
            penalty += prefs["avoid_day_weight"]

    penalty += prefs["day_weight"] * len(by_day)

    for times in by_day.values():
        times.sort()
        for (s1, e1), (s2, e2) in zip(times, times[1:]):
            penalty += prefs["gap_weight"] * max(0, s2 - e1) / 60

    n_warnings = sum(len(opt.warnings) for opt in options)
    penalty += prefs["unknown_weight"] * n_warnings
    return round(penalty, 2)


# ---------------------------------------------------------------------------
# 6. The solver: backtracking + MRV + forward checking

def solve(courses, required, optional=(), completed=(), min_credits=12,
          max_credits=18, prefs=None, top_k=3, max_nodes=200_000,
          allow_unknown_times=False):
    """Find the top_k best schedules.

    required : course IDs the student MUST take
    optional : course IDs the student would LIKE to take (solver may skip them)
    completed: course IDs already passed (for prereq checks)
    """
    prefs = {**DEFAULT_PREFS, **(prefs or {})}
    completed = {normalize_course_id(c) for c in completed}
    report = {"blocked": {}, "warnings": {}, "nodes_explored": 0, "hit_node_limit": False}

    # --- Build domains (and filter by prereqs) ---
    domains = {}
    for raw_id in list(required) + list(optional):
        cid = normalize_course_id(raw_id)
        if cid not in courses:
            report["blocked"][cid] = "not offered this term"
            if raw_id in required:
                return [], report
            continue
        status, msg = eligibility(courses[cid], completed)
        if status == "blocked":
            report["blocked"][cid] = msg
            if raw_id in required:
                return [], report          # can't take a required course -> no schedule
            continue
        opts = build_domain(cid, courses[cid], allow_unknown_times)
        if status == "unknown":
            report["warnings"][cid] = msg
            for o in opts:
                o.warnings.append(f"{cid}: {msg}")
        if not opts:
            report["blocked"][cid] = "no sections with known meeting times"
            if raw_id in required:
                return [], report
            continue
        if raw_id in optional:
            opts = opts + [SKIP]           # optional courses may be left out
        domains[cid] = opts

    # Value ordering: try options that look nicest on their own first.
    for cid in domains:
        domains[cid].sort(key=lambda o: 1e9 if o is SKIP else score_schedule([o], prefs))

    best = []          # a heap holding the top_k schedules found so far
    counter = itertools.count()   # tie-breaker so the heap never compares Options
    max_possible = {cid: max((o.credits for o in d if o is not SKIP), default=0)
                    for cid, d in domains.items()}

    def backtrack(assignment, remaining):
        report["nodes_explored"] += 1
        if report["nodes_explored"] > max_nodes:
            report["hit_node_limit"] = True  # results are "best found", not guaranteed best
            return  # safety stop so a huge search can't run forever

        chosen = [o for o in assignment.values() if o is not SKIP]
        credits = sum(o.credits for o in chosen)

        # Credit constraint, checked early ("pruning"):
        if credits > max_credits:
            return
        if credits + sum(max_possible[c] for c in remaining) < min_credits:
            return  # even taking everything left can't reach the minimum

        if not remaining:   # every course has a value -> complete schedule
            if min_credits <= credits <= max_credits:
                score = score_schedule(chosen, prefs)
                item = (-score, next(counter), list(chosen), credits)
                if len(best) < top_k:
                    heapq.heappush(best, item)
                elif -score > best[0][0]:
                    heapq.heapreplace(best, item)
            return

        # MRV: choose the course with the fewest options left
        var = min(remaining, key=lambda c: len(remaining[c]))
        others = {c: d for c, d in remaining.items() if c != var}

        for value in remaining[var]:
            # Forward checking: remove options in other courses that clash with `value`
            if value is SKIP:
                new_remaining = others
            else:
                new_remaining = {}
                dead_end = False
                for c, dom in others.items():
                    kept = [o for o in dom if o is SKIP or not blocks_overlap(o.blocks, value.blocks)]
                    if not kept:
                        dead_end = True    # some course has no options left -> stop now
                        break
                    new_remaining[c] = kept
                if dead_end:
                    continue
            assignment[var] = value
            backtrack(assignment, new_remaining)
            del assignment[var]              # undo = "backtrack"

    backtrack({}, domains)

    results = []
    for neg_score, _, chosen, credits in sorted(best, key=lambda x: -x[0]):
        results.append(format_schedule(chosen, credits, -neg_score))
    return results, report


# ---------------------------------------------------------------------------
# 7. Output in a plain format other parts of the project can read

def format_schedule(options, credits, score):
    entries = []
    for opt in sorted(options, key=lambda o: o.course_id):
        for sec in opt.sections:
            times = [
                f"{'/'.join(m['days'])} {m['start']}-{m['end']}" if m["start"] else sec["schedule_type"]
                for m in sec["meetings"]
            ]
            entries.append({"course": opt.course_id, "section": sec["id"],
                            "type": sec["type"], "times": times})
        if opt.alternatives:
            alt = [" + ".join(s["id"] for s in combo) for combo in opt.alternatives]
            entries[-1]["same_time_alternatives"] = alt
    warnings = sorted({w for o in options for w in o.warnings})
    return {"score": score, "credits": credits, "sections": entries, "warnings": warnings}


def print_schedule(rank, sched):
    print(f"\n#{rank}  penalty={sched['score']}  credits={sched['credits']}")
    for e in sched["sections"]:
        print(f"   {e['course']:<11} {e['type']:<11} sec {e['section']:<6} {', '.join(e['times'])}")
        if e.get("same_time_alternatives"):
            print(f"   {'':<11} (same times also in: {', '.join(e['same_time_alternatives'][:5])}"
                  f"{' ...' if len(e['same_time_alternatives']) > 5 else ''})")
    for w in sched["warnings"]:
        print(f"   ! {w}")


if __name__ == "__main__":
    courses = load_courses("2026-fall")
    print(f"Loaded {len(courses)} courses for Fall 2026")

    # Example student: finished intro CS + discrete math + calc I
    results, report = solve(
        courses,
        required=["CSCI 23500", "CSCI 26000", "MATH 15500"],
        optional=["CSCI 26500", "STAT 21300", "CSCI 39542"],
        completed=["CSCI 12700", "CSCI 13500", "CSCI 15000", "CSCI 16000", "MATH 15000"],
        min_credits=12, max_credits=16,
        prefs={"avoid_days": ["Fri"], "earliest_start": "10:00"},
    )
    print("Blocked:", report["blocked"])
    print("Unverified:", report["warnings"])
    print("Search nodes explored:", report["nodes_explored"])
    for i, s in enumerate(results, 1):
        print_schedule(i, s)