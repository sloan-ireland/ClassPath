import itertools
from csp_solver import (normalize_course_id, blocks_overlap, check_prereq,
                        load_courses, build_domain, solve, section_blocks)


def test_normalize_ids():
    assert normalize_course_id("Csci 235") == "CSCI 23500"
    assert normalize_course_id("CSCI-26000") == "CSCI 26000"
    assert normalize_course_id("MATH 155") == "MATH 15500"
    assert normalize_course_id("MATH 101EN") == "MATH 101EN"


def test_overlap_rules():
    a = [("Mon", 600, 675)]                       # Mon 10:00-11:15
    assert blocks_overlap(a, [("Mon", 660, 720)])  # starts during a -> clash
    assert not blocks_overlap(a, [("Mon", 675, 750)])  # back-to-back -> fine
    assert not blocks_overlap(a, [("Tue", 600, 675)])  # different day -> fine


def test_prereq_all_any():
    expr = {"all": ["CSCI 13500", {"any": ["CSCI 16000", "CSCI 24500"]}]}
    assert check_prereq(expr, {"CSCI 13500", "CSCI 24500"})
    assert not check_prereq(expr, {"CSCI 13500"})
    assert not check_prereq(expr, {"CSCI 16000"})


def test_lecture_plus_recitation_domain():
    courses = load_courses("2026-fall")
    opts = build_domain("CSCI 13500", courses["CSCI 13500"], allow_unknown_times=True)
    assert all(len(o.sections) == 2 for o in opts)
    assert all({s["type"] for s in o.sections} == {"lecture", "recitation"} for o in opts)


def test_results_never_clash_and_respect_credits():
    courses = load_courses("2026-fall")
    scenarios = [
        dict(required=["MATH 12550", "STAT 11300", "CSCI 12700"], optional=["CSCI 15000"],
             completed=["MATH 12500"], min_credits=9, max_credits=15),
        dict(required=["CSCI 23500", "CSCI 26000", "MATH 15500"],
             optional=["CSCI 26500", "STAT 21300"],
             completed=["CSCI 12700", "CSCI 13500", "CSCI 15000", "CSCI 16000", "MATH 15000"],
             min_credits=12, max_credits=16),
    ]
    for sc in scenarios:
        results, _ = solve(courses, **sc)
        assert results, f"expected schedules for {sc}"
        for sched in results:
            assert sc["min_credits"] <= sched["credits"] <= sc["max_credits"]
            ids = {(e["course"], e["section"]) for e in sched["sections"]}
            secs = [s for c in courses.values() for s in c["sections"]
                    if (normalize_course_id(c["course_id"]), s["id"]) in ids]
            for a, b in itertools.combinations(secs, 2):
                assert not blocks_overlap(section_blocks(a), section_blocks(b))
        scores = [s["score"] for s in results]
        assert scores == sorted(scores), "results should be best-first"


def test_missing_prereq_blocks_required_course():
    courses = load_courses("2026-fall")
    results, report = solve(courses, required=["CSCI 33500"], completed=[],
                            min_credits=0, max_credits=18)
    assert results == [] and "CSCI 33500" in report["blocked"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("PASS", name)