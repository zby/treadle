# Positioning

**Status:** working positioning, 2026-10-15. Nothing is implemented yet; every
claim below about Treadle is a design target unless it links a measurement.

## One line

**Write an agent workflow once, as ordinary Pydantic AI code. Step it from
Claude Code, Codex or pi, where the harness's own agents do the work, and run it
natively in Pydantic AI when you are ready.**

Short form: *your code is the graph; any harness is the runtime.* The first half
is Samuel Colvin's ([The code IS the graph](https://x.com/samuelcolvin/status/2110055467007303729),
2026-10-13); credit it where it is used. Treadle is not a Pydantic project and
must not read as endorsed by Pydantic.

## The name

A treadle is the foot pedal that drives a loom or a lathe: each push turns the
machine one step, and a motor can later take the foot's place. In Treadle the
orchestrating agent pushes the pedal (`treadle step`), the workflow is the
machine, and progressive codification is fitting the motor. See
[ADR 005](../adr/005-name-treadle.md).

## Who it is for

People who already run multi-agent processes through coding-agent harnesses:
implement–verify–repair loops, code-base analyses, review relays, research
fan-outs. Today such a process usually lives in one of three places:

1. **Prose instructions** (a skill, an `AGENTS.md` procedure, a long prompt).
   The orchestrating agent must remember every step, branch and retry count;
   it drifts, forgets, and loses the run when its context ends. Nothing can be
   resumed by another session.
2. **Harness-specific automation** (one harness's sub-agent features, hooks or
   SDK). It works in that harness only.
3. **A workflow engine or graph library.** Durable and explicit, but needs a
   server or a graph DSL, and its workers are API model calls, not the harness's
   agents with their tools, files and subscriptions.

Treadle moves the control flow into code without giving up the harness. The
secondary audience is Pydantic AI users who want the same workflow to be
drivable from a harness, for development, cheap runs on a subscription, or work
that needs a full agent at a step.

## What a worker is

In Pydantic AI a model call is a model call. Under `treadle step` the same call
is answered by whoever takes the prompt: a harness sub-agent with its own tools
(shell, editor, browser), a person, or a script. The workflow sees a typed
answer either way. This is the main practical difference from every route that
runs model calls directly: the steps of a Treadle workflow can be whole agent
sessions, and workers keep full freedom in how they produce the answer
(a commit marks the end, [ADR 002](../adr/002-commit-attests-answer-files-by-hash.md)).

## Three claims, in order

1. **Portable and resumable.** One workflow file runs under any harness and
   natively in Pydantic AI. Progress lives in a store of plain files, not in an
   agent's context, so any session or harness can continue a run, and
   `treadle step` doubles as the status command.
2. **Progressive codification.** The orchestrator's job is small because the
   code makes every decision; when the agent slips, its duties move into hooks,
   then a driver script, then a native run, with the workflow unchanged
   ([ADR 003](../adr/003-progressive-codification.md)).
3. **Build-system semantics.** A monadic build in the sense of *Build Systems à
   la Carte*: dependencies discovered by running the code, results stored under
   content hashes, finished work never redone. The calls a workflow waits on are
   a task list, so a tracker comes for free, without a configuration language
   for workflows.

The tracker is the consequence, not the headline.

## What it is not

- **Not an agent framework.** Pydantic AI is the framework and the workflow
  language. "Harness-independent" describes who runs the steps, not how the
  workflow is written.
- **Not a production durable-execution engine.** For long-running services use
  Pydantic AI with Temporal (or DBOS, Prefect). Treadle is a bridge into that,
  not a rival.
- **Not a sandbox for model-written workflows.** That is Monty and Pydantic AI
  Harness's `run_workflow`. Treadle runs trusted code people write and reuse.
- **Not a scheduler, queue or server.** A CLI and a directory.

## Neighbours

| Neighbour | What it gives | How Treadle relates |
|---|---|---|
| Prose procedures and skills | Zero setup; uses the harness's agents | Treadle keeps the harness's agents but moves control flow into code that cannot drift |
| Pydantic AI, run directly | Typed agents, real models | Same workflow file; Treadle adds harness-driven runs and a path into it |
| Pydantic AI Harness `run_workflow` + Monty | Model-written choreography, sandboxed, snapshots | Complementary: model-written vs reused workflows; a Monty route for Treadle is on the Later list |
| Temporal (with Pydantic AI) | Production durability by replay | Same replay model; Treadle needs no server and lets any harness answer the activities |
| Graph libraries (LangGraph and others) | Explicit graphs, checkpoints | Treadle takes the code-is-the-graph side: no graph DSL, joins are typed Python |
| Build tools (Make, Shake, Bazel, Luigi) | Dynamic dependencies, cached results | Same theory; tasks are agents and people, not deterministic commands |
| Task trackers (Beads, Linear, Jira automation) | Tasks, dependencies, status | Treadle's tasks are what a workflow waits on; lifecycles are code, not rules |

Claims in this table about other systems are from their documentation and the
sources in ADR 001, not from comparative runs.

## Claims we cannot make yet

- That orchestrating agents follow step output reliably (stage 2 measures it).
- That replay stays cheap for long workflows (memoized tasks are deferred).
- That agents with Pydantic AI tools work under `treadle step` (not in version 1).
- Any performance or cost comparison with other routes.

## Open questions

- Should the README lead with the harness user (claim 1) or the Pydantic AI user
  (the bridge)? Current choice: the harness user.
- How much of the tracker story belongs on the front page.
- Whether "your code is the graph; any harness is the runtime" stays as the
  tagline once Treadle has its own vocabulary.
