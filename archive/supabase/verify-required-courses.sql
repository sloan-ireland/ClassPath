-- Read-only behavioral checks using the live elective rules.
-- Inputs represent distinct, already-qualified course credits, not raw attempts.
with scenarios(name, expected_credits, courses) as (values
  ('empty',0,'[]'::jsonb),
  ('below_threshold',0,'[{"course_id":"CSCI 13500","credits":4}]'::jsonb),
  ('exclusive_boundary',0,'[{"course_id":"CSCI 13600","credits":1}]'::jsonb),
  ('above_threshold',3,'[{"course_id":"CSCI 13700","credits":3}]'::jsonb),
  ('ordinary_elective',3,'[{"course_id":"CSCI 35000","credits":3}]'::jsonb),
  ('excluded_above_threshold',0,'[{"course_id":"CSCI 18100","credits":3},{"course_id":"CSCI 22700","credits":3},{"course_id":"CSCI 23200","credits":3}]'::jsonb),
  ('required_course_not_elective',0,'[{"course_id":"CSCI 15000","credits":4},{"course_id":"CSCI 49900","credits":4}]'::jsonb),
  ('wrong_subject',0,'[{"course_id":"MATH 25000","credits":4}]'::jsonb),
  ('lower_combined_cap',3,'[{"course_id":"CSCI 39100","credits":1},{"course_id":"CSCI 39200","credits":2},{"course_id":"CSCI 39300","credits":3}]'::jsonb),
  ('upper_combined_cap',9,'[{"course_id":"CSCI 49600","credits":4},{"course_id":"CSCI 49700","credits":4},{"course_id":"CSCI 49800","credits":4}]'::jsonb),
  ('both_caps_reach_target',12,'[{"course_id":"CSCI 39100","credits":3},{"course_id":"CSCI 39300","credits":3},{"course_id":"CSCI 49600","credits":6},{"course_id":"CSCI 49800","credits":6}]'::jsonb),
  ('uncapped_target',12,'[{"course_id":"CSCI 35000","credits":3},{"course_id":"CSCI 35300","credits":3},{"course_id":"CSCI 40500","credits":3},{"course_id":"CSCI 43500","credits":3}]'::jsonb)
), eligible as (
  select s.name,c.course_id,c.credits,m.cap_group,k.maximum_credits
  from scenarios s cross join public.elective_rules r
  cross join lateral jsonb_to_recordset(s.courses) as c(course_id text,credits numeric)
  left join public.elective_cap_courses m on m.rule_id=r.rule_id and m.course_id=c.course_id
  left join public.elective_credit_caps k on k.rule_id=m.rule_id and k.cap_group=m.cap_group
  where r.rule_id='cs' and split_part(c.course_id,' ',1)=r.subject
    and split_part(c.course_id,' ',2)::integer > r.minimum_course_number_exclusive
    and not exists (select 1 from public.elective_exclusions x where x.rule_id=r.rule_id and x.course_id=c.course_id)
    and (not r.exclude_required_courses or not exists (select 1 from public.required_courses q where q.course_id=c.course_id))
), buckets as (
  select name,coalesce(cap_group,course_id) as bucket,
    case when maximum_credits is null then sum(credits)
      else least(sum(credits),maximum_credits) end as applied_credits
  from eligible group by name,coalesce(cap_group,course_id),maximum_credits
), actual as (
  select name,sum(applied_credits) as eligible_credits from buckets group by name
)
select s.name,s.expected_credits,coalesce(a.eligible_credits,0) as actual_credits,
  coalesce(a.eligible_credits,0)=s.expected_credits as passed,
  greatest(r.required_credits-coalesce(a.eligible_credits,0),0) as remaining_credits
from scenarios s left join actual a using(name)
cross join public.elective_rules r where r.rule_id='cs' order by s.name;
