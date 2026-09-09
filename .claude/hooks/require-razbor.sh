#!/bin/bash
# Gate on the fixer's own contract: a brief with no `## Razbor` section is a design
# skipped, not a design done elsewhere. The fixer subagent is told to implement
# exactly what Razbor specifies and never re-open the root cause — a brief missing
# the section gives it nothing to implement against, and it would improvise instead.
# Enforcing this in a hook, not in the fixer's own prompt, is the point: text in a
# system prompt is an influence the model can drift from under pressure to be
# helpful; a hook is machinery that runs whether or not the model remembers to check.
#
# Manual test:
#   printf '{"tool_input":{"subagent_type":"fixer","prompt":"just fix it"}}' | bash .claude/hooks/require-razbor.sh
#   printf '{"tool_input":{"subagent_type":"factory-librarian","prompt":"where is X"}}' | bash .claude/hooks/require-razbor.sh

INPUT=$(cat)

SUBAGENT=$(printf '%s' "$INPUT" | jq -r '.tool_input.subagent_type // empty' 2>/dev/null)
if [ "$SUBAGENT" != "fixer" ]; then
  exit 0
fi

PROMPT=$(printf '%s' "$INPUT" | jq -r '.tool_input.prompt // empty' 2>/dev/null)

missing=""
if ! printf '%s' "$PROMPT" | grep -q '^## Razbor'; then
  missing="the whole \`## Razbor\` heading"
else
  for item in Facts Root Measurement Contradiction Separation Deltas Proof; do
    if ! printf '%s' "$PROMPT" | grep -qE "^- \[x\].*${item}"; then
      missing="${missing:+$missing, }$item"
    fi
  done
fi

if [ -n "$missing" ]; then
  reason="fixer brief has no usable Razbor section — missing: ${missing}. Run /razbor in the main session and paste its output as a \`## Razbor\` section with all seven \`- [x]\` checklist lines before delegating."
  reason=$(printf '%s' "$reason" | sed 's/\\/\\\\/g; s/"/\\"/g')
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}' "$reason"
fi
exit 0
