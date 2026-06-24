#!/usr/bin/env python3
"""Quick admin stats for diagnostic writing AI quality."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.supabase_client import get_supabase


def main() -> int:
    sb = get_supabase()

    recent = (
        sb.table("diagnostic_ai_evaluations")
        .select(
            "evaluation_source, model_name, prompt_version, overall_band, evaluated_at"
        )
        .eq("evaluation_type", "writing")
        .order("evaluated_at", desc=True)
        .limit(10)
        .execute()
    ).data or []

    print("=== Last 10 writing evaluations ===")
    for row in recent:
        print(
            f"  {row.get('evaluated_at', '?')[:19]}  "
            f"source={row.get('evaluation_source')}  "
            f"band={row.get('overall_band')}  "
            f"model={row.get('model_name') or '-'}  "
            f"prompt={row.get('prompt_version')}"
        )

    ai_rows = (
        sb.table("diagnostic_ai_evaluations")
        .select("overall_band")
        .eq("evaluation_type", "writing")
        .eq("evaluation_source", "ai")
        .execute()
    ).data or []

    fallback_rows = (
        sb.table("diagnostic_ai_evaluations")
        .select("id")
        .eq("evaluation_type", "writing")
        .eq("evaluation_source", "fallback")
        .execute()
    ).data or []

    if ai_rows:
        avg = sum(float(r["overall_band"]) for r in ai_rows) / len(ai_rows)
        print(f"\nAI evaluations: count={len(ai_rows)}  avg_band={avg:.2f}")
    else:
        print("\nAI evaluations: count=0")

    print(f"Fallback evaluations: count={len(fallback_rows)}")

    if len(fallback_rows) > len(ai_rows) and len(ai_rows) + len(fallback_rows) > 0:
        print(
            "\nWARNING: More fallback than AI rows — Groq may not be reached reliably.",
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
