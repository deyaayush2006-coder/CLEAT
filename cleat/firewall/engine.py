"""Deterministic policy engine that decides allow, approve or block for one attempted tool call.

Pure Python with no LLM involvement (invariant I-1). Hard rules are checked first (I-4)
and the most restrictive matching rule wins (I-7)."""
