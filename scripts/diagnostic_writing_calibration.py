#!/usr/bin/env python3
"""Run labeled Task 1 sample essays through Groq for band calibration (dry-run, no DB).

Usage:
  cd backend && .venv/bin/python scripts/diagnostic_writing_calibration.py

Requires GROQ_API_KEY in .env. Does not persist to diagnostic_ai_evaluations.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import reload_settings
from app.diagnostic.writing_evaluator import _call_groq_evaluation
from app.writing.evaluation import word_count

TASK1_QUESTION = (
    "The bar chart below shows the proportion of workers who used four different modes "
    "of transport to travel to work in Tokyo, Berlin, São Paulo, and Toronto in 2022."
)


@dataclass(frozen=True)
class CalibrationSample:
    label: str
    human_band: float
    essay: str


SAMPLES: list[CalibrationSample] = [
    CalibrationSample(
        label="band_4.5",
        human_band=4.5,
        essay=(
            "The chart show transport in four city. Car is high in Sao Paulo. "
            "Tokyo use public transport more. Berlin has cycling. Toronto is mixed. "
            "Cars are popular in some places."
        ),
    ),
    CalibrationSample(
        label="band_5.0",
        human_band=5.0,
        essay=(
            "The bar chart compares four cities and four transport types in 2022. "
            "Cars are the biggest in Sao Paulo while Tokyo prefers buses and trains. "
            "Berlin has more cyclists than the others. Walking is small everywhere. "
            "Overall each city is different."
        ),
    ),
    CalibrationSample(
        label="band_5.5",
        human_band=5.5,
        essay=(
            "The chart illustrates commuter transport in Tokyo, Berlin, Sao Paulo and Toronto in 2022. "
            "Overall, cars are common but public transport leads in Tokyo. "
            "In Sao Paulo around sixty percent use cars which is the highest. "
            "Berlin shows more cycling than other cities at about twenty percent. "
            "Toronto is fairly balanced between cars and public transport. "
            "Walking remains the smallest category in all four cities."
        ),
    ),
    CalibrationSample(
        label="band_6.0",
        human_band=6.0,
        essay=(
            "The bar chart compares how workers travelled to work in four cities in 2022, "
            "using cars, public transport, cycling and walking. "
            "Overall, car use was highest in Sao Paulo while Tokyo relied most on public transport. "
            "In Tokyo, public transport accounted for roughly fifty-five percent compared with "
            "about thirty percent for cars. Berlin had a more even split between cars and public "
            "transport, but stood out for cycling at nearly twenty percent. "
            "Sao Paulo had the largest car share at around sixty percent, with public transport "
            "much lower. Toronto was similar to Berlin for cars but had slightly more walking. "
            "In conclusion, transport patterns varied considerably across the four cities."
        ),
    ),
    CalibrationSample(
        label="band_6.5",
        human_band=6.5,
        essay=(
            "The bar chart presents the proportion of commuters using four transport modes in "
            "Tokyo, Berlin, Sao Paulo and Toronto in 2022. "
            "Overall, private cars dominated in Sao Paulo whereas Tokyo was characterised by "
            "heavy public transport use. "
            "Tokyo recorded the highest public transport share at approximately fifty-five percent, "
            "well above its car usage of thirty percent. By contrast, Sao Paulo showed the reverse "
            "pattern, with cars at sixty percent and public transport at only twenty-five percent. "
            "Berlin displayed a relatively balanced profile, though cycling reached nearly twenty "
            "percent, the highest among the cities. Toronto mirrored Berlin for car use but recorded "
            "marginally higher walking. "
            "To summarise, while cars remained significant in most cities, Tokyo was notable for "
            "public transport and Berlin for cycling uptake."
        ),
    ),
    CalibrationSample(
        label="band_7.0",
        human_band=7.0,
        essay=(
            "The bar chart compares the percentage of workers commuting by car, public transport, "
            "cycling and walking in Tokyo, Berlin, Sao Paulo and Toronto in 2022. "
            "Overall, car dependency was most pronounced in Sao Paulo, while Tokyo exhibited the "
            "greatest reliance on public transport and Berlin led in cycling. "
            "In Tokyo, public transport constituted the largest share at roughly fifty-five percent, "
            "nearly double the proportion using cars. Berlin presented a more diversified pattern: "
            "cars and public transport each accounted for about thirty-five percent, with cycling "
            "contributing a further twenty percent—the highest figure across the sample. "
            "Sao Paulo contrasted sharply with the other cities, as approximately sixty percent of "
            "commuters travelled by car, whereas public transport represented only a quarter of trips. "
            "Toronto occupied a middle position, with car use near forty percent and modest walking "
            "levels slightly above those in Sao Paulo. "
            "In summary, the data reveal marked variation in commuting habits, with Sao Paulo "
            "favouring private vehicles and Tokyo prioritising mass transit."
        ),
    ),
    CalibrationSample(
        label="under_length_40w",
        human_band=4.0,
        essay=(
            "The chart shows transport in four cities. Cars are high in Brazil. "
            "Tokyo likes trains. Berlin cycles more."
        ),
    ),
    CalibrationSample(
        label="minimal_30w",
        human_band=3.5,
        essay=" ".join(["word"] * 30),
    ),
    CalibrationSample(
        label="strong_7.5",
        human_band=7.5,
        essay=(
            "The bar chart compares commuter transport preferences across Tokyo, Berlin, "
            "Sao Paulo and Toronto in 2022, broken down into cars, public transport, cycling "
            "and walking. "
            "Overall, Sao Paulo exhibited the strongest dependence on cars, whereas Tokyo was "
            "distinguished by exceptionally high public transport usage; Berlin, meanwhile, recorded "
            "the most substantial cycling share. "
            "More specifically, public transport accounted for approximately fifty-five percent of "
            "commuters in Tokyo, almost twice the car share. In Berlin, cars and public transport "
            "were evenly matched at around thirty-five percent each, but nearly one in five workers "
            "cycled—considerably higher than in the remaining cities. "
            "Sao Paulo presented the most car-oriented profile, with private vehicles representing "
            "roughly sixty percent of journeys, while public transport lagged at twenty-five percent. "
            "Toronto fell between these extremes, combining moderate car use with slightly elevated "
            "walking figures relative to Sao Paulo. "
            "Overall, the chart highlights contrasting urban mobility cultures, from car-dominated "
            "commuting in Sao Paulo to transit-oriented patterns in Tokyo and active travel in Berlin."
        ),
    ),
    CalibrationSample(
        label="excellent_8.0",
        human_band=8.0,
        essay=(
            "The bar chart illustrates the proportion of workers who commuted by car, public "
            "transport, cycling or walking in Tokyo, Berlin, Sao Paulo and Toronto in 2022. "
            "Overall, it is clear that commuting patterns diverged substantially: Sao Paulo was "
            "heavily car-dependent, Tokyo was dominated by public transport, and Berlin stood out "
            "for its comparatively high cycling uptake. "
            "Looking at the details, Tokyo recorded the highest public transport share at about "
            "fifty-five percent, nearly double private car use. Berlin displayed a more balanced "
            "distribution between cars and public transport—each near thirty-five percent—while "
            "cycling contributed a further twenty percent, the peak value among the four cities. "
            "By contrast, Sao Paulo exhibited the most pronounced car reliance at roughly sixty "
            "percent, with public transport limited to a quarter of commuters. Toronto occupied "
            "an intermediate position, with car usage close to forty percent and walking marginally "
            "higher than in Sao Paulo. "
            "In conclusion, the data underscore significant cross-city variation in modal choice, "
            "suggesting differing infrastructure priorities and commuter behaviour across these "
            "major urban centres."
        ),
    ),
]


async def _evaluate_sample(sample: CalibrationSample) -> dict:
    ev, _, prompt_version, model = await _call_groq_evaluation(
        task_part=1,
        question=TASK1_QUESTION,
        essay=sample.essay,
    )
    words = word_count(sample.essay)
    delta = ev.overall_band - sample.human_band
    return {
        "label": sample.label,
        "human": sample.human_band,
        "words": words,
        "ai": ev.overall_band,
        "delta": delta,
        "ta": ev.task_achievement,
        "coh": ev.coherence,
        "lex": ev.lexical_resource,
        "gram": ev.grammar,
        "prompt": prompt_version,
        "model": model,
    }


def _print_table(rows: list[dict]) -> None:
    header = f"{'label':<18} {'human':>5} {'words':>5} {'ai':>5} {'delta':>6} {'TA':>4} {'Coh':>4} {'Lex':>4} {'Gram':>4}"
    print(header)
    print("-" * len(header))
    within_half = 0
    for r in rows:
        ok = abs(r["delta"]) <= 0.5
        within_half += int(ok)
        flag = "ok" if ok else "!!"
        print(
            f"{r['label']:<18} {r['human']:>5.1f} {r['words']:>5} {r['ai']:>5.1f} "
            f"{r['delta']:>+6.1f} {r['ta']:>4.1f} {r['coh']:>4.1f} {r['lex']:>4.1f} {r['gram']:>4.1f}  {flag}"
        )
    print()
    print(f"Within ±0.5 of human label: {within_half}/{len(rows)}")
    if rows:
        print(f"Prompt: {rows[0]['prompt']}  Model: {rows[0]['model']}")


async def main() -> int:
    settings = reload_settings()
    if not settings.groq_api_key.strip():
        print("ERROR: GROQ_API_KEY not set in .env")
        return 1

    print(f"Running {len(SAMPLES)} calibration essays (dry-run, no DB writes)...\n")
    rows: list[dict] = []
    for sample in SAMPLES:
        try:
            rows.append(await _evaluate_sample(sample))
        except Exception as exc:
            print(f"FAILED {sample.label}: {exc}")
    _print_table(rows)
    print("\nTarget for marketing funnel: majority within ±0.5 of human estimate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
