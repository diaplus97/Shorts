"""Korean naturalness: register, endings, nominalisation, deictic reference.

Before this module the repository had no language check at all -- grepping the
quality package for a hangul range, ``is_korean`` or ``lang`` returned nothing.
Every "Korean" rule was a positive substring match (banned nouns, banned
openings), all of which an English script passes trivially, and a narration
written entirely in the register the owner complained about returned zero
issues.

The thresholds are measured from ``tests/fixtures/benchmark/water_reclamation.txt``,
a script that works, rather than chosen. Where the benchmark and the pipeline's
own output differed by an order of magnitude, that gap is the check.

What this catches is *shapes*: a calqued idiom, an empty light verb, a
narration made of pronouns. Whether a sentence actually sounds like a person is
not decidable here and the module does not pretend otherwise -- that needs a
human ear or a Korean-native judge.

Deliberately **not** here: an ending-variety check. The benchmark ends every
one of its thirteen sentences in a ~니다 form and reads fine, so an overall
same-ending ratio measures Korean formal register, not monotony. What does read
as monotone is a *run* of identical endings, and
``speech_contract.check_ending_repetition`` already checks exactly that over the
speech units.
"""

from __future__ import annotations

import re

from ..config import ContentContract
from ..domain import ScriptResult
from .report import QAIssue, error, warning

_HANGUL = re.compile(r"[가-힣]")
_LATIN = re.compile(r"[A-Za-z]")

#: Deictic reference: "것들", "그 상태", "이 흐름". Each one is a noun slot the
#: writer declined to fill, and the viewer can only fill it from the picture.
DEICTIC = re.compile(
    r"것들|것은|것이|것을|것만|것도|그것|이것|저것"
    r"|이 흐름|그 흐름|이 길|그 길|이 과정|그 상태|이런 것|그런 것|무언가"
)

#: "이것이 물재생센터입니다" -- the closing formula, which names the subject
#: rather than dodging it, and which the benchmark itself ends on. Removed
#: before counting so one idiomatic close cannot fail a short script.
_NAMING_CLOSE = re.compile(
    r"(?:이것|그것|이게|그게)이?\s*(?:바로\s*)?(?:[가-힣]+\s*){1,4}?(?:입니다|이죠|예요)"
)

#: An inanimate subject plus a semantically empty verb -- the shape of
#: "나머지는 중력이 합니다", a word-for-word calque of an English documentary
#: idiom. Korean puts the work in the verb, so an empty verb reads as translated.
LIGHT_VERB = re.compile(
    r"[가-힣]{2,}(?:이|가)\s*(?:합니다|한다|해요|하죠)\b"
    r"|(?:을|를)\s*(?:수행|실시|담당|진행)(?:합니다|한다|해요|하죠)"
)

#: Nominalisation: "속도의 향상을 가능하게 합니다" where "속도가 빨라집니다"
#: says the same thing. Bureaucratic Korean, and unreadable aloud.
NOMINALISATION = re.compile(
    r"[가-힣]{2,}의\s+[가-힣]{2,}(?:을|를)\s*(?:가능하게|하게)\s*(?:합니다|한다)"
    r"|(?:을|를)\s*(?:가능하게|용이하게)\s*(?:합니다|한다)"
)


def hangul_ratio(text: str) -> float:
    """Share of letters that are hangul. Guards against an English script."""
    hangul = len(_HANGUL.findall(text))
    latin = len(_LATIN.findall(text))
    total = hangul + latin
    return hangul / total if total else 1.0


def check_language(script: ScriptResult, contract: ContentContract) -> list[QAIssue]:
    """The narration has to actually be Korean."""
    minimum = getattr(contract.script, "min_hangul_ratio", 0.0)
    if minimum <= 0:
        return []
    ratio = hangul_ratio(script.narration)
    if ratio >= minimum:
        return []
    return [
        error(
            "script_not_korean",
            f"only {ratio:.0%} of the letters are hangul (needs {minimum:.0%}); "
            "the narration is read aloud in Korean",
        )
    ]


def check_translationese(script: ScriptResult, contract: ContentContract) -> list[QAIssue]:
    """Calqued idioms and empty light verbs, per beat so the message can point."""
    if not getattr(contract.script, "ban_translationese", True):
        return []

    issues: list[QAIssue] = []
    for beat in script.beats:
        for match in LIGHT_VERB.finditer(beat.text):
            issues.append(
                error(
                    "script_light_verb",
                    f"beat {beat.id}: '{match.group().strip()}' puts the meaning in the "
                    "noun and leaves the verb empty. Say what the thing physically does "
                    "-- 중력이 끌어내립니다, not 중력이 합니다.",
                )
            )
        for match in NOMINALISATION.finditer(beat.text):
            issues.append(
                error(
                    "script_nominalisation",
                    f"beat {beat.id}: '{match.group().strip()}' is bureaucratic Korean. "
                    "Use the plain verb -- 속도가 빨라집니다, not 속도의 향상을 가능하게 합니다.",
                )
            )
    return issues


def check_deictic_density(script: ScriptResult, contract: ContentContract) -> list[QAIssue]:
    """A narration made of pronouns only works with the picture in front of you.

    This is the check for the complaint that the script leaves everything to the
    video: if the sentences never name their subject, audio alone carries nothing.
    """
    limit = getattr(contract.script, "max_deictic_per_100_chars", 0.0)
    if limit <= 0:
        return []

    text = script.narration
    chars = len(text.replace(" ", ""))
    if chars < 100:
        return []

    found = DEICTIC.findall(_NAMING_CLOSE.sub("", text))
    density = len(found) / chars * 100
    if density <= limit:
        return []

    sample = ", ".join(sorted(set(found))[:6])
    return [
        error(
            "script_deictic_density",
            f"{len(found)} deictic references in {chars} characters ({density:.2f} per 100, "
            f"limit {limit:.2f}): {sample}. Each one is a noun the narration declined to "
            "name, so the sentence only means something while the matching shot is on "
            "screen. Name the thing.",
        )
    ]


def check_named_anchors(script: ScriptResult, contract: ContentContract) -> list[QAIssue]:
    """Numbers and names are what make an explanation feel real.

    The benchmark carries roughly one numeral per 120 characters -- 1976년,
    100만 톤, 축구장 100개, 150 → 20 -- and the pipeline's own output carried
    none at all. A script with no quantity and no name is describing a generic
    machine rather than a particular one.
    """
    minimum = getattr(contract.script, "min_numerals", 0)
    if minimum <= 0:
        return []

    numerals = re.findall(r"\d", script.narration)
    if len(numerals) >= minimum:
        return []

    return [
        warning(
            "script_no_anchors",
            f"the narration contains {len(numerals)} digits (wants at least {minimum}). "
            "A quantity the sources establish -- a size, a count, a year, a rate -- is "
            "what separates this machine from any machine. Do not invent one; if the "
            "claims carry no number, this is a research problem.",
        )
    ]


def check_korean_register(script: ScriptResult, contract: ContentContract) -> list[QAIssue]:
    """Every language check, in one call for the writer's validate closure."""
    return [
        *check_language(script, contract),
        *check_translationese(script, contract),
        *check_deictic_density(script, contract),
        *check_named_anchors(script, contract),
    ]
