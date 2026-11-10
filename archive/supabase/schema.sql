-- ClassPath scheduling snapshot. Apply only to the new ClassPath project.
create table public.terms (
  term_id text primary key check (term_id ~ '^20[0-9]{2}-(spring|summer|fall|winter)$'),
  timezone text not null
);

-- A course can have different academic requirements in different semesters.
create table public.courses (
  term_id text not null references public.terms (term_id),
  course_id text not null,
  title text not null check (length(title) > 0),
  credits_min numeric(6,2),
  credits_max numeric(6,2),
  prerequisites text,
  corequisites text,
  pre_or_corequisites text,
  primary key (term_id, course_id),
  check ((credits_min is null and credits_max is null)
    or (credits_min is not null and credits_max is not null
        and credits_min >= 0 and credits_max >= credits_min))
);
create index courses_course_id_idx on public.courses (course_id);

create table public.sections (
  section_id text primary key,
  term_id text not null,
  course_id text not null,
  section_name text not null,
  dependency_overrides jsonb not null default '{}'::jsonb,
  foreign key (term_id, course_id) references public.courses (term_id, course_id),
  check (jsonb_typeof(dependency_overrides) = 'object'),
  check (dependency_overrides - array['prerequisites','corequisites','pre_or_corequisites'] = '{}'::jsonb),
  check (not (dependency_overrides ? 'prerequisites') or jsonb_typeof(dependency_overrides->'prerequisites') in ('string','null')),
  check (not (dependency_overrides ? 'corequisites') or jsonb_typeof(dependency_overrides->'corequisites') in ('string','null')),
  check (not (dependency_overrides ? 'pre_or_corequisites') or jsonb_typeof(dependency_overrides->'pre_or_corequisites') in ('string','null'))
);
create index sections_course_idx on public.sections (term_id, course_id);

create table public.meetings (
  section_id text not null references public.sections (section_id),
  meeting_index integer not null check (meeting_index >= 0),
  days text[] not null,
  start_time time without time zone,
  end_time time without time zone,
  schedule_type text not null check (schedule_type in ('scheduled','asynchronous','unknown')),
  start_date date,
  end_date date,
  end_day_offset smallint not null check (end_day_offset in (0,1)),
  primary key (section_id, meeting_index),
  check (days <@ array['Mon','Tue','Wed','Thu','Fri','Sat','Sun']::text[]),
  check (start_date is null or end_date is null or start_date <= end_date),
  check (
    (schedule_type = 'scheduled' and cardinality(days) > 0
      and start_time is not null and end_time is not null
      and ((end_time > start_time and end_day_offset = 0)
        or (end_time < start_time and end_day_offset = 1)))
    or
    (schedule_type in ('asynchronous','unknown') and cardinality(days) = 0
      and start_time is null and end_time is null and end_day_offset = 0)
  )
);

comment on table public.courses is 'Term-specific course records; prerequisite text is not a verified executable rule.';
comment on column public.sections.dependency_overrides is 'Only section-specific prerequisite/corequisite text. An explicit JSON null differs from an absent override.';
comment on table public.meetings is 'Local wall times in the timezone of the related term. Unknown meetings must not be treated as conflict-free.';

alter table public.terms enable row level security;
alter table public.courses enable row level security;
alter table public.sections enable row level security;
alter table public.meetings enable row level security;

-- Dashboard/admin and trusted backend access only until app access is specified.
revoke all on public.terms, public.courses, public.sections, public.meetings from public, anon, authenticated;
grant select, insert, update, delete on public.terms, public.courses, public.sections, public.meetings to service_role;
