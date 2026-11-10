select 'terms' as dataset, count(*) as rows from public.terms
union all select 'course_offerings', count(*) from public.courses
union all select 'distinct_courses', count(distinct course_id) from public.courses
union all select 'sections', count(*) from public.sections
union all select 'meetings', count(*) from public.meetings
union all select 'section_dependency_overrides', count(*) from public.sections where dependency_overrides <> '{}'::jsonb;

select t.term_id,
  (select count(*) from public.courses c where c.term_id=t.term_id) as courses,
  (select count(*) from public.sections s where s.term_id=t.term_id) as sections,
  (select count(*) from public.meetings m join public.sections s using(section_id) where s.term_id=t.term_id) as meetings
from public.terms t order by t.term_id;

select schedule_type, count(*) from public.meetings group by schedule_type order by schedule_type;

select c.relname as table_name, c.relrowsecurity as rls_enabled,
  has_table_privilege('anon', c.oid, 'select') as anon_read,
  has_table_privilege('authenticated', c.oid, 'select') as authenticated_read,
  has_table_privilege('service_role', c.oid, 'select,insert,update,delete') as backend_access
from pg_class c join pg_namespace n on n.oid=c.relnamespace
where n.nspname='public' and c.relname in ('terms','courses','sections','meetings')
order by c.relname;

-- The combined prerequisite-or-corequisite condition remains distinct.
select term_id, course_id, prerequisites, corequisites, pre_or_corequisites
from public.courses where course_id='STAT 11300' order by term_id;

-- Section-specific dependencies have not been silently applied to the whole course.
select s.term_id, s.course_id, s.section_id, s.dependency_overrides
from public.sections s
where s.dependency_overrides <> '{}'::jsonb
order by s.term_id, s.course_id, s.section_id limit 5;
