# Live run against heffrey78/gh-project-sandbox

41 calls to 14 tools in 47 s; 2 errors; median 990 ms

Tools called: add_comment, create_decision, create_requirement, create_task, export_docs, get_record, get_status, link_records, query_records, save_project, set_status, setup_repository, unlink_records, update_record

### setup

`setup_repository({})`

```
heffrey78/gh-project-sandbox: 13 labels in use, 0 created; all were already there.
```

### status, before

`get_status({})`

```
Tracker: heffrey78/gh-project-sandbox
Requirements (4): Validated 2, Deprecated 2
Decisions (4): Accepted 2, Superseded 2
Tasks (6): Complete 6

No tasks are ready to start: no open tasks remain.
```

### project

`save_project({"title": "Live run 2026-10-03 08:01:38", "purpose": "Prove the server against real GitHub.", "success_criteria": ["Every tool works"]})`

```
Created project 4: Live run 2026-10-03 08:01:38
https://github.com/heffrey78/gh-project-sandbox/milestone/4
```

### requirement

`create_requirement({"title": "Search stays fast", "type": "NFUNC", "priority": "P1", "current_state": "A query takes 900 ms.", "desired_state": "Search stays quick.", "project": "Live run 2026-10-03 08:01:38"})`

```
Created requirement #146: Search stays fast
https://github.com/heffrey78/gh-project-sandbox/issues/146
Status: Draft

Warnings:
- No acceptance_criteria: every requirement needs them to be checkable later.
- No validation_metrics: an NFUNC requirement needs the number that settles it.
```

### fill the thin requirement

`update_record({"id": 146, "fields": {"acceptance_criteria": ["p95 under 50 ms"], "validation_metrics": ["p95 at 10k notes"]}})`

```
Updated requirement #146: changed acceptance_criteria, validation_metrics
```

### second requirement

`create_requirement({"title": "Export works", "type": "FUNC", "priority": "P3", "current_state": "No export.", "desired_state": "Markdown export.", "acceptance_criteria": ["A note exports"]})`

```
Created requirement #147: Export works
https://github.com/heffrey78/gh-project-sandbox/issues/147
Status: Draft
```

### refused: through Approved

`set_status({"ids": 147, "status": "Implemented"})`

```
#147: refused: Draft to Implemented passes through Approved, which is a decision of its own and is never made on the way to something else. Move it to Approved first
No record moved.
```

### approve

`set_status({"ids": "#146", "status": "Approved", "comment": "Approved for the live run"})`

```
#146: Draft → Under Review → Approved
```

### decision

`create_decision({"title": "Scan every note", "context": "Small sets.", "decision": "Scan.", "addresses": [146]})`

```
Created decision #148: Scan every note
https://github.com/heffrey78/gh-project-sandbox/issues/148
Status: Proposed
```

### accept

`set_status({"ids": 148, "status": "Accepted"})`

```
#148: Proposed → Accepted
```

### refused: rewrite an accepted decision

`update_record({"id": 148, "fields": {"decision": "Index."}})`

```
Decision #148 is Accepted and is not rewritten. To correct it, pass `amendment`; to change direction, create a new decision and link_records(source=<new>, type='supersedes', target=148)
```

### amend

`update_record({"id": 148, "amendment": "Scanning measured 900 ms at 10k notes.", "reason": "Benchmark"})`

```
Amended decision #148. Its text is unchanged; the amendment shows beneath it.
```

### newer decision

`create_decision({"title": "Use an index", "context": "Scanning is too slow.", "decision": "Build an inverted index.", "addresses": [146]})`

```
Created decision #149: Use an index
https://github.com/heffrey78/gh-project-sandbox/issues/149
Status: Proposed
```

### supersede

`link_records({"source": 149, "type": "supersedes", "target": 148})`

```
Linked: #149 supersedes #148
#148 is now Superseded (was Accepted).
```

### accept newer

`set_status({"ids": 149, "status": "Accepted"})`

```
#149: Proposed → Accepted
```

### read superseded

`get_record({"id": 148})`

```
Decision #148: Scan every note
https://github.com/heffrey78/gh-project-sandbox/issues/148
Status: Superseded | Project: Live run 2026-10-03 08:01:38

Context:
Small sets.

Decision:
Scan.
> Amendment (2026-10-03, heffrey78): Scanning measured 900 ms at 10k notes. Reason: Benchmark

Addresses:
- #146 Search stays fast [Approved, P1]

Superseded by:
- #149 Use an index [Accepted]
```

### task

`create_task({"title": "Build the index", "parent": 146, "priority": "P1", "test_plan": ["unit tests"], "effort": "M"})`

```
Created task #150: Build the index
https://github.com/heffrey78/gh-project-sandbox/issues/150
Status: Not Started
Under: #146 Search stays fast [Approved, P1]
```

### subtask

`create_task({"title": "Tokenise notes", "parent": 150, "priority": "P2"})`

```
Created task #151: Tokenise notes
https://github.com/heffrey78/gh-project-sandbox/issues/151
Status: Not Started
Under: #150 Build the index [Not Started, P1]
```

### task blocked by another

`create_task({"title": "Benchmark", "parent": 146, "priority": "P1", "test_plan": ["run the benchmark"], "blocked_by": [150]})`

```
Created task #152: Benchmark
https://github.com/heffrey78/gh-project-sandbox/issues/152
Status: Not Started
Under: #146 Search stays fast [Approved, P1]
Blocked by: #150
```

### ready

`query_records({"ready": true})`

```
- #151 Tokenise notes [Not Started, P2]
```

### dashboard, mid-run

`get_status({})`

```
Tracker: heffrey78/gh-project-sandbox
Requirements (6): Draft 1, Approved 1, Validated 2, Deprecated 2
Decisions (6): Accepted 3, Superseded 3
Tasks (9): Not Started 3, Complete 6

Projects:
- 4 Live run 2026-10-03 08:01:38: requirements 1, tasks 0/2 complete

Ready to start (1):
- #151 Tokenise notes [Not Started, P2]

Waiting on other work (1):
- #152 Benchmark [Not Started, P1]: waits on #150 (Not Started)
```

### start

`set_status({"ids": 151, "status": "In Progress"})`

```
#151: Not Started → In Progress
```

### block

`set_status({"ids": 151, "status": "Blocked", "comment": "Waiting on a tokeniser choice"})`

```
#151: In Progress → Blocked
```

### dashboard, blocked

`get_status({})`

```
Tracker: heffrey78/gh-project-sandbox
Requirements (6): Draft 1, Approved 1, Validated 2, Deprecated 2
Decisions (6): Accepted 3, Superseded 3
Tasks (9): Not Started 2, Blocked 1, Complete 6

Projects:
- 4 Live run 2026-10-03 08:01:38: requirements 1, tasks 0/2 complete

No tasks are ready to start: of 3 open, 1 Blocked, 1 waiting on unfinished work.

Blocked (1):
- #151 Tokenise notes [Blocked, P2]: Waiting on a tokeniser choice

Waiting on other work (1):
- #152 Benchmark [Not Started, P1]: waits on #150 (Not Started)
```

### finish subtask

`set_status({"ids": 151, "status": "Complete", "commit": "abc1234", "evidence": "9 tests pass"})`

```
#151: Blocked → Complete
  warning: It is still Blocked.
```

### finish parent

`set_status({"ids": 150, "status": "Complete", "evidence": "index builds"})`

```
#150: Not Started → Complete
```

### extra link

`link_records({"source": 147, "type": "blocked_by", "target": 146})`

```
Linked: #147 blocked_by #146
```

### remove it

`unlink_records({"source": 147, "type": "blocked_by", "target": 146})`

```
Unlinked: #147 blocked_by #146
```

### bench, two steps

`set_status({"ids": [152], "status": "In Progress"})`

```
#152: Not Started → In Progress
```

### bench done

`set_status({"ids": 152, "status": "Complete", "evidence": "p95 37 ms"})`

```
#152: In Progress → Complete
```

### comment

`add_comment({"id": 146, "comment": "Live run: all work done."})`

```
Commented on requirement #146.
```

### work complete

`query_records({"work_complete": true})`

```
- #146 Search stays fast [Approved, P1]
```

### validate

`set_status({"ids": 146, "status": "Validated", "evidence": "p95 37 ms at 10k notes"})`

```
#146: Approved → Implemented → Validated
```

### trace

`get_record({"id": 146, "include": ["comments", "history"]})`

```
Requirement #146: Search stays fast
https://github.com/heffrey78/gh-project-sandbox/issues/146
Status: Validated | Priority: P1 | Type: NFUNC | Project: Live run 2026-10-03 08:01:38
Progress: 2/2 tasks complete

Current state:
A query takes 900 ms.

Desired state:
Search stays quick.

Acceptance criteria:
- [ ] p95 under 50 ms

Validation metrics:
- p95 at 10k notes

Tasks:
- #150 Build the index [Complete, P1]
  - #151 Tokenise notes [Complete, P2]
- #152 Benchmark [Complete, P1]

Decisions:
- #148 Scan every note [Superseded]
- #149 Use an index [Accepted]

Comments (3):
- 2026-10-03 heffrey78: **Status:** Draft → Under Review → Approved

Approved for the live run
- 2026-10-03 heffrey78: Live run: all work done.
- 2026-10-03 heffrey78: **Status:** Approved → Implemented → Validated
**Evidence:** p95 37 ms at 10k notes

History (15):
- 2026-10-03T12:01:42Z heffrey78: milestoned Live run 2026-10-03 08:01:38
- 2026-10-03T12:01:43Z heffrey78: labeled requirement
- 2026-10-03T12:01:43Z heffrey78: labeled P1
- 2026-10-03T12:01:45Z heffrey78: commented **Status:** Draft → Under Review → Approved
- 2026-10-03T12:01:45Z heffrey78: labeled status:approved
- 2026-10-03T12:01:47Z heffrey78: cross-referenced #148
- 2026-10-03T12:01:52Z heffrey78: cross-referenced #149
- 2026-10-03T12:01:58Z heffrey78: sub_issue_added #150
- 2026-10-03T12:02:01Z heffrey78: sub_issue_added #152
- 2026-10-03T12:02:10Z heffrey78: blocking_added #147
- 2026-10-03T12:02:10Z heffrey78: blocking_removed #147
- 2026-10-03T12:02:14Z heffrey78: commented Live run: all work done.
- 2026-10-03T12:02:16Z heffrey78: closed
- 2026-10-03T12:02:16Z heffrey78: unlabeled status:approved
- 2026-10-03T12:02:17Z heffrey78: commented **Status:** Approved → Implemented → Validated
```

### project view

`get_record({"project": "Live run 2026-10-03 08:01:38"})`

```
Project 4: Live run 2026-10-03 08:01:38
https://github.com/heffrey78/gh-project-sandbox/milestone/4
State: open | Requirements: 1 | Tasks: 2/2 complete

Purpose:
Prove the server against real GitHub.

Success criteria:
- Every tool works

Requirements:
- #146 Search stays fast [Validated, P1]

Decisions:
- #148 Scan every note [Superseded]
- #149 Use an index [Accepted]
```

### search

`query_records({"search": "index", "kind": "decision"})`

```
- #26 Use an index [Accepted]
- #55 Use an index [Accepted]
- #149 Use an index [Accepted]
```

### export

`export_docs({"output_directory": "/tmp/tmpxd_pqjeg", "project": "Live run 2026-10-03 08:01:38"})`

```
Exported 6 records from heffrey78/gh-project-sandbox:
- /tmp/tmpxd_pqjeg/live-run-2026-10-03-08-01-38-requirements.md
- /tmp/tmpxd_pqjeg/live-run-2026-10-03-08-01-38-decisions.md
- /tmp/tmpxd_pqjeg/live-run-2026-10-03-08-01-38-tasks.md
- /tmp/tmpxd_pqjeg/live-run-2026-10-03-08-01-38-diagram.md
Diagram: 6 records drawn, 0 retired left out, 0 over the limit.
```

### drift made by hand

`get_status({})`

```
Tracker: heffrey78/gh-project-sandbox
Requirements (6): Approved 1, Validated 3, Deprecated 2
Decisions (6): Accepted 3, Superseded 3
Tasks (9): Complete 9

Projects:
- 4 Live run 2026-10-03 08:01:38: requirements 1, tasks 2/2 complete

No tasks are ready to start: no open tasks remain.

Drift (1): state on GitHub that the lifecycle's rules would not produce
- #147 has 2 status labels (Under Review, Approved); read as Approved
```

### retire

`set_status({"ids": 147, "status": "Deprecated", "comment": "Live run over"})`

```
#147: Approved → Deprecated
```

### close project

`save_project({"project": "Live run 2026-10-03 08:01:38", "state": "closed"})`

```
Updated project 4 (Live run 2026-10-03 08:01:38): changed state
```

### status, after

`get_status({})`

```
Tracker: heffrey78/gh-project-sandbox
Requirements (6): Validated 3, Deprecated 3
Decisions (6): Accepted 3, Superseded 3
Tasks (9): Complete 9

No tasks are ready to start: no open tasks remain.
```

Records: {"req": 146, "other": 147, "decision": 148, "newer": 149, "build": 150, "tokenise": 151, "bench": 152}
