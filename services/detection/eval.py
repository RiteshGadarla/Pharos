"""Per-class IoU and F1 on a held-out split. See PLAN.md section 5, "Evaluation".

Deferred at the user's direction (task 3 in PLAN.md section 18 was
explicitly skipped for now). Blocked on the same dependency PLAN.md
section 4A item 4 names: the labeled 5-class oil-spill dataset, which
is distributed by request or through a mirror.

Never surface the model card's self-reported 0.9668 F1 anywhere. This
module's job is producing the honest number to replace it with.
"""

if __name__ == "__main__":
    raise SystemExit(
        "eval.py: not yet implemented, deferred pending the labeled dataset, see PLAN.md section 4A item 4"
    )
