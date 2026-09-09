---
name: razbor
description: Analysis before a change — engine and service code, the bot and its conversation with the user, the wrapper around HyperFrames and its configuration, the makeup of Claude Code itself (skills, agents, hooks, rules, claude -p). Apply when behaviour is being fixed, an architecture is being chosen, or a bug is being investigated; when this is already the second fix for the same symptom; when the requirements contradict each other.
---

# Razbor

A fix aimed at the symptom breeds the next fix: in large systems, 15 to 24 percent of
bug fixes turn out to be wrong themselves, and regression tests let them through.
What follows is what stops that chain.

**Do NOT propose or make a change until the root cause is named and the contradiction
is written down — or it is explicitly stated that there is no contradiction.**

Copy the checklist and tick items off as you go:

```
Razbor:
- [ ] 1. Facts — ask the librarians about the class of place
- [ ] 2. Root — a chain of causes upward, checked at each link
- [ ] 3. Measurement — the price of both states, in numbers
- [ ] 4. Contradiction — by the template, with a price
- [ ] 5. Separation — separate, relocate, only then add
- [ ] 6. Deltas — what this puts in motion
- [ ] 7. Proof — a command and its output, before the word "done"
```

The main session runs this skill. Executors (the `fixer` subagent) do not run
`/razbor` themselves — they receive its output as a finished `## Razbor` section in
their brief and implement against it. Splitting it this way is deliberate: the
subagent that writes code should not also be the one deciding whether its own root
cause is real.

## 1. Facts

Ask a librarian about a **class** of places, not the ones you already have in mind:
"every place where …", not "check these two". That is how the third place turns up —
for instance a hint shown to the user that names a command which doesn't exist.

Our code and the bot → `factory-librarian`. The framework → `hyperframes-librarian`.
The makeup of Claude Code itself → `claude-code-librarian`. None of the three goes
near prod or a dependency's own source — that part you do yourself.

The root can sit outside all three — in git, in the OS, in someone else's installer.
If no source explains the measurement, the source hasn't been found yet.

## 2. Root

A chain of causes upward, checked at every link: remove this cause — does the path to
the symptom close? The root does not sit there ready-made; it gets chosen, and it
usually gets chosen wherever looking got tiresome.

A separate question: is this symptom a trace of our own earlier decision? Then fix
that decision, or the chain only gets longer. Earlier attempts at the same symptom
are worth finding in history and opening.

## 3. Measurement

Measurement comes before the contradiction. The price of both states — in numbers, by
a command and its output. This is what flips a task on its head: the avatar seams
turn out to make the reel more expensive, not cheaper, and the repeat screen happens
once a month across fifty restarts.

A measurement showing "nothing changed" gets checked for whether it read anything at all — a cache or an index can keep returning the old answer.

Measure on the artefact the failing path itself produced — the file the service generated for the
failing job (the composed script, the rendered frame, the written plan), not a file you swapped in
by hand. A hand-swapped file proves the component; only the generated one proves the path. Before
naming a root cause, open that generated artefact and check whether the fix is even in it: four
caption fixes in a row were verified on swapped files and test material while the job folder kept
composing from a component staged in a step that never re-runs.

## 4. Contradiction

> Needs **[the parameter]** to be **[state A]** for **[benefit 1]**, but
> **[state B]** for **[benefit 2]**; rejected **[what]**, accepting the price
> **[which]**.

The template does not let you lie: a line with no price does not get written, and a
tautology like "needs to be in one place, but in several" shows up immediately.

Not writable at all — there is no contradiction, and that is an answer, not a dead
end. It usually means the measurement is too thin (back to step 3), or both states
pull the same direction (the cost model is wrong — name where it came from). A bug
with no contradiction gets fixed by root cause and separation.

## 5. Separation

Separation comes before addition. New conflicts are what an addition breeds: every
element is a new interface, a new failure mode, and a new prop to hold it up. So
first separate the contradictory states — by time, by place, by condition, by
scale — and separately by **the unit being billed**: what money or time is actually
charged for, and whether that is the unit this change is cutting.

If separation doesn't work, relocate the responsibility onto something that already
exists: the framework, our own wrapper code, a dependency, Claude Code itself. Adding
something new is the last resort — say why separation didn't fit when it is chosen.

Stuck on an irreversible step — make the decision reversible instead of choosing
between options: behind a flag, an interface, or deferred until there is more data.

## 6. Deltas

What this puts in motion — as deltas against what is already promised: what new calls
and entities appear, what measured number moves, what subtasks arise, what changes
for callers, in tests, and in prod, and by which observable sign it will become clear
the decision was wrong.

A subtask with nothing to solve it, without which the decision doesn't work, disqualifies the decision — back to step 5 or step 2.

## 7. Proof

**The word "done" only travels with a command and its output.** A retelling of the
result without the command's output does not count as proof.

If the symptom comes back after the fix, the root named at step 2 was wrong — go back
to step 2, don't prop up what was already found.

### The output artefact: a `## Razbor` section for the fixer's brief

When this analysis is done, its result is not a conversation — it is a `## Razbor`
section pasted into the brief handed to the `fixer` subagent. A `PreToolUse` hook on
the `Agent` tool enforces this mechanically: a brief for `fixer` with no usable
`## Razbor` section is rejected before the subagent ever starts (see
`.claude/hooks/require-razbor.sh`). Write exactly seven lines, each starting with
`- [x]` and each naming its step, followed by one sentence:

```
## Razbor
- [x] Facts — <what the librarians confirmed, and which one>
- [x] Root — <the cause, named, one link at a time verified>
- [x] Measurement — <the price of both states, in numbers>
- [x] Contradiction — <filled template, or "none" with why>
- [x] Separation — <what got separated or relocated, before anything got added>
- [x] Deltas — <what moves: calls, tests, prod, the falsification signal>
- [x] Proof — <the command that will be run to prove it, or the output already in hand>
```

After the seven lines, list the files and functions to change, the tests to add, and
— for a composition change — the evidence frame the fixer must produce.

For a **composition change** (captions, schemas, positions, contrast), the proof step
is a `/snapshot-check` frame taken before merge, not a green gate: gates are checked
in step 7 same as any other measurement, but a rendered frame is what actually shows
whether the change worked.

## When it isn't needed

A conversation with no change, reading, message wording, a typo — the cost of being
wrong there is a few words on screen. Line count is not the measure here: a line in a
version pin, in a model name, or in billing is the most expensive kind of line this
project has.

A ready-made solution already exists in the framework or in our own code — use it.
The object of the change is named ambiguously — that's a question for Vasya, not a
razbor.
