"""Profile generation pipeline (framework.md §4.3): identity → traits → occurrence-derived
priors → LLM extraction with evidence → reconciliation → draft profiles for review.

Generated values are weak priors and hypotheses. Status and policy tiers are never generated
here: they come only from status providers (``wildlife_scanner.policy.statuses``).
"""

PIPELINE_VERSION = "profilegen-0.1"
