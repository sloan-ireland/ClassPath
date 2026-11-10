-- ClassPath kxjppqyawhfjclbidtwc only. Implements the user-agreed checklist.
begin;

create table public.required_courses (
  course_id text primary key check (course_id ~ '^(CSCI|MATH|STAT) [0-9]{5}$'),
  title text not null check (length(title) > 0),
  credits numeric(6,2) not null check (credits > 0),
  course_group text not null check (course_group in ('Required CS', 'Required Math'))
);
comment on table public.required_courses is
  'Every row is individually required. Match course_id to semester offerings without a term-specific foreign key. Credits counted once per completed course.';

create table public.elective_rules (
  rule_id text primary key,
  subject text not null check (subject ~ '^[A-Z]+$'),
  minimum_course_number_exclusive integer not null check (minimum_course_number_exclusive >= 0),
  required_credits numeric(6,2) not null check (required_credits > 0),
  exclude_required_courses boolean not null default true check (exclude_required_courses)
);

create table public.elective_exclusions (
  rule_id text not null references public.elective_rules(rule_id),
  course_id text not null check (course_id ~ '^[A-Z]+ [0-9]{5}$'),
  primary key (rule_id, course_id)
);

create table public.elective_credit_caps (
  rule_id text not null references public.elective_rules(rule_id),
  cap_group text not null,
  maximum_credits numeric(6,2) not null check (maximum_credits >= 0),
  primary key (rule_id, cap_group)
);

create table public.elective_cap_courses (
  rule_id text not null,
  course_id text not null check (course_id ~ '^[A-Z]+ [0-9]{5}$'),
  cap_group text not null,
  primary key (rule_id, course_id),
  foreign key (rule_id, cap_group) references public.elective_credit_caps(rule_id, cap_group)
);
create index elective_cap_courses_group_idx on public.elective_cap_courses(rule_id, cap_group);
comment on table public.elective_rules is
  'Eligibility: matching subject, number strictly above threshold, no exclusion, and not a required course. Use actual qualified earned credits, not credits per section. Scheduled courses are projected only.';
comment on table public.elective_credit_caps is
  'Apply maximum_credits to the combined earned credits of all member courses, not individually to each course. Excess credits do not count toward the elective target.';

insert into public.required_courses(course_id,title,credits,course_group) values
  ('CSCI 12700','Introduction to Computer Science',3,'Required CS'),
  ('CSCI 13500','Software Design & Analysis I',4,'Required CS'),
  ('CSCI 15000','Discrete Structures',4,'Required CS'),
  ('CSCI 16000','Computer Architecture I',3,'Required CS'),
  ('CSCI 23500','Software Design & Analysis II',3,'Required CS'),
  ('CSCI 26000','Computer Architecture II',3,'Required CS'),
  ('CSCI 26500','Computer Theory I',3,'Required CS'),
  ('CSCI 33500','Software Design & Analysis III',3,'Required CS'),
  ('CSCI 34000','Operating Systems',3,'Required CS'),
  ('CSCI 49900','Advanced Applications: A Capstone for Majors',4,'Required CS'),
  ('MATH 15000','Calculus I',4,'Required Math'),
  ('MATH 15500','Calculus II',4,'Required Math'),
  ('MATH 16000','Matrix Algebra',3,'Required Math'),
  ('STAT 21300','Introduction to Applied Statistics',3,'Required Math');

insert into public.elective_rules values ('cs','CSCI',13600,12,true);
insert into public.elective_exclusions(rule_id,course_id) values
  ('cs','CSCI 12000'),('cs','CSCI 12100'),('cs','CSCI 13200'),('cs','CSCI 13300'),
  ('cs','CSCI 18100'),('cs','CSCI 18200'),('cs','CSCI 18300'),
  ('cs','CSCI 22700'),('cs','CSCI 23200'),('cs','CSCI 23300');
insert into public.elective_credit_caps values
  ('cs','csci_391_393',3),('cs','csci_496_498',9);
insert into public.elective_cap_courses values
  ('cs','CSCI 39100','csci_391_393'),('cs','CSCI 39200','csci_391_393'),
  ('cs','CSCI 39300','csci_391_393'),('cs','CSCI 49600','csci_496_498'),
  ('cs','CSCI 49700','csci_496_498'),('cs','CSCI 49800','csci_496_498');

alter table public.required_courses enable row level security;
alter table public.elective_rules enable row level security;
alter table public.elective_exclusions enable row level security;
alter table public.elective_credit_caps enable row level security;
alter table public.elective_cap_courses enable row level security;
-- Preserve the existing project's backend-only access model.
revoke all on public.required_courses,public.elective_rules,public.elective_exclusions,
  public.elective_credit_caps,public.elective_cap_courses from public,anon,authenticated;
grant select,insert,update,delete on public.required_courses,public.elective_rules,
  public.elective_exclusions,public.elective_credit_caps,public.elective_cap_courses to service_role;

commit;
