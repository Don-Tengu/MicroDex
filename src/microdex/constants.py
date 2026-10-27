"""Fixed limits for the phase-1 subprocess tool.

Phase 2 decides how these limits are chosen and shown to the user. Phase 1
only needs values that keep one command from hanging the exercise. Read the
attributes on each call (`constants.EXEC_TIMEOUT_SECONDS`); do not copy them
into another module at import time.
"""

EXEC_TIMEOUT_SECONDS = 30
EXEC_OUTPUT_CAP_BYTES = 100_000
TRUNCATION_MARKER = "\n...[truncated]"

# sample -> tools -> sample counts as several super-steps. 40 tool rounds fit.
RECURSION_LIMIT = 100
