"""Beat order and causal linkage (spec section 14).

The arc is a *sequence*: hook, then reveal, then the process beats in physical
order, then the surprise that follows from them, then the close. Until this
module existed the only script-level look at beat purposes built a ``set``
first, so a script running ``hook, closing, surprise, process, reveal`` passed
without a single issue. A viewer feels that within about eight seconds -- the
video does not go anywhere -- so it is checked as an error, not a warning.

What is checked here is order and linkage, both decidable from the text:

* **Order.** A purpose sequence either moves forward through the arc or it does
  not, and the message can name the beat that broke it.
* **Linkage.** Something has to join one sentence to the next besides the cut.
  Counting causal connectives does not judge whether the reasoning is good, but
  a narration with none of them is a list of facts, and the work of relating
  them falls on the picture.

Deliberately **not** here: a single-subject or single-chain check, for the
reported failure where a script toured a checkout scanner, then airport
baggage, then a warehouse conveyor. Two implementations were measured and both
were unsound:

* Extracting the noun before 은/는/이/가 does not find subjects in Korean. The
  marker 는 is also the adnominal verb ending, so it captures verb stems
  (확인하, 이동하, 나누), and Korean drops subjects freely -- only two of seven
  process sentences in the mock ATM script carry a subject marker at all, and
  the broken-chain fixture carries none.
* Lexical overlap between adjacent beats does not separate the cases. The
  benchmark script scores 15% and a good mock script 17%, against 0% for the
  broken one: real, but far too narrow a margin to fail a run on.

Doing this properly needs a morphological analyser. Until then it belongs in
the writer prompt, which states the requirement in prose, rather than in a gate
that would reject good scripts.
"""

from __future__ import annotations

import re
from itertools import pairwise

from ..config import ContentContract
from ..domain import BeatPurpose, ScriptBeat, ScriptResult
from .report import QAIssue, error

#: Where each purpose sits in the arc. TRANSITION is deliberately absent: it is
#: connective tissue and may appear between any two beats.
ARC_POSITION: dict[BeatPurpose, int] = {
    BeatPurpose.HOOK: 0,
    BeatPurpose.CONTEXT: 1,
    BeatPurpose.PROBLEM: 2,
    BeatPurpose.REVEAL: 3,
    BeatPurpose.PROCESS: 4,
    BeatPurpose.SURPRISE: 5,
    BeatPurpose.CLOSING: 6,
}

#: A Short with no reveal never says what the thing is; with no surprise it is
#: a list of steps that stops rather than ends. PROBLEM is required for the same
#: reason the reference Short opens on one: without "here is the obvious answer,
#: and here is why it does not work", the mechanism that follows has nothing to
#: be an answer *to*.
REQUIRED_PURPOSES = (
    BeatPurpose.HOOK,
    BeatPurpose.PROBLEM,
    BeatPurpose.REVEAL,
    BeatPurpose.SURPRISE,
    BeatPurpose.CLOSING,
)

#: Connectives that carry a beat back to the one before it. The benchmark
#: narration averages roughly one per 100 characters; a script with none is
#: asserting facts side by side rather than building on them.
CAUSAL_CONNECTIVES = (
    "그래서",
    "그러면",
    "그런데",
    "그럼",
    "하지만",
    "이에",
    "따라서",
    "덕분",
    "때문",
    "대신",
    "결국",
    "반면",
    "그러나",
)

#: Clause-internal causal endings. "녹아 있어서", "공급되면", "된 뒤" carry the
#: same linkage inside a sentence rather than between two.
CAUSAL_ENDINGS = re.compile(r"(?:아서|어서|해서|되면|으면|[가-힣]면|은 뒤|는 뒤|니까|므로|도록)")


def _arc_beats(beats: list[ScriptBeat]) -> list[ScriptBeat]:
    """Beats that carry an arc position, i.e. everything but transitions."""
    return [beat for beat in beats if beat.purpose in ARC_POSITION]


def check_beat_arc(script: ScriptResult, contract: ContentContract) -> list[QAIssue]:
    """The beat sequence must move forward through the arc."""
    if not getattr(contract.script, "arc_order_required", True):
        return []
    beats = _arc_beats(script.beats)
    if not beats:
        return [error("script_arc_empty", "script has no beats carrying an arc purpose")]

    issues: list[QAIssue] = []

    if beats[0].purpose is not BeatPurpose.HOOK:
        issues.append(
            error(
                "script_arc_order",
                f"the first beat {beats[0].id} is '{beats[0].purpose}'; a Short opens on the hook",
            )
        )
    if beats[-1].purpose is not BeatPurpose.CLOSING:
        issues.append(
            error(
                "script_arc_order",
                f"the last beat {beats[-1].id} is '{beats[-1].purpose}'; "
                "a Short ends on the closing",
            )
        )

    present = {beat.purpose for beat in beats}
    for required in REQUIRED_PURPOSES:
        if required not in present:
            issues.append(
                error(
                    "script_arc_missing",
                    f"no beat with purpose '{required}'. Without it the script "
                    f"{_why_required(required)}",
                )
            )

    # Name the beat that broke the order, and what it came after. A message the
    # writer can act on is the difference between a retry that fixes something
    # and a retry that reshuffles at random.
    for previous, current in pairwise(beats):
        if ARC_POSITION[current.purpose] < ARC_POSITION[previous.purpose]:
            issues.append(
                error(
                    "script_arc_order",
                    f"beat {current.id} ({current.purpose}) comes after "
                    f"{previous.id} ({previous.purpose}); the arc only moves forward",
                )
            )

    return issues


def _why_required(purpose: BeatPurpose) -> str:
    return {
        BeatPurpose.HOOK: "opens on nothing the viewer wants answered",
        BeatPurpose.PROBLEM: (
            "never says why the obvious answer fails, so the mechanism that "
            "follows is a list of steps rather than an answer to anything"
        ),
        BeatPurpose.CONTEXT: "never says where this sits or how big it is",
        BeatPurpose.REVEAL: "never says what the thing actually is",
        BeatPurpose.SURPRISE: "is a list of steps that stops rather than ends",
        BeatPurpose.CLOSING: "runs out rather than landing",
    }.get(purpose, "is incomplete")


def check_beat_size(script: ScriptResult, contract: ContentContract) -> list[QAIssue]:
    """Beats have to be movements, not fragments.

    The reference Short is seven paragraphs averaging 87 characters. The first
    real output here was twenty beats averaging 17, with half of them not even
    ending a sentence -- one sentence split across two beats. At that size the
    arc means nothing, because no beat is large enough to *do* anything, and
    the result reads as a list of parts rather than an explanation.
    """
    clause = contract.script
    beats = _arc_beats(script.beats)
    if len(beats) < 3:
        return []

    issues: list[QAIssue] = []

    minimum = getattr(clause, "min_beat_chars", 0)
    # The hook has its own, much tighter budget, so averaging it in penalises a
    # script for obeying a different rule. The benchmark's hook is 30 characters
    # against a body averaging 74.
    body = [b for b in beats if b.purpose is not BeatPurpose.HOOK]
    if minimum > 0 and body:
        average = sum(len(beat.text.replace(" ", "")) for beat in body) / len(body)
        if average < minimum:
            issues.append(
                error(
                    "script_beats_too_small",
                    f"{len(body)} beats averaging {average:.0f} characters (wants at least "
                    f"{minimum}). A beat is a movement of two or three sentences, not one "
                    "sentence. At this size the narration is a list of parts.",
                )
            )

    # A sentence split across two beats makes the arc labels meaningless: the
    # second half carries a purpose it does not actually serve.
    unfinished = [b.id for b in beats if b.text.strip() and b.text.strip()[-1] not in ".?!…"]
    if len(unfinished) > len(beats) * 0.25:
        issues.append(
            error(
                "script_beats_split_sentences",
                f"{len(unfinished)} of {len(beats)} beats do not end a sentence "
                f"({', '.join(unfinished[:8])}). Each beat is a whole thought; a sentence "
                "running across two of them makes the purpose labels meaningless.",
            )
        )

    limit = getattr(clause, "max_process_beats", 0)
    process = [b for b in beats if b.purpose is BeatPurpose.PROCESS]
    if limit > 0 and len(process) > limit:
        issues.append(
            error(
                "script_too_many_steps",
                f"{len(process)} process beats, over the limit of {limit}. Nobody holds "
                "that many steps. Group them into fewer, fuller movements and cut what "
                "the answer does not need.",
            )
        )
    return issues


def check_causal_linkage(script: ScriptResult, contract: ContentContract) -> list[QAIssue]:
    """Beats have to be joined by language, not only by the cut.

    Without connectives the narration is a list of true sentences, and the work
    of relating them falls entirely on the picture -- which is the failure the
    benchmark script avoids and this pipeline did not.
    """
    clause = contract.script
    minimum = getattr(clause, "min_causal_per_100_chars", 0.0)
    if minimum <= 0:
        return []

    text = script.narration
    chars = len(text.replace(" ", ""))
    if chars < 100:
        return []

    found = sum(text.count(word) for word in CAUSAL_CONNECTIVES)
    found += len(CAUSAL_ENDINGS.findall(text))
    density = found / chars * 100
    if density >= minimum:
        return []

    return [
        error(
            "script_no_causal_linkage",
            f"{found} causal connectives in {chars} characters ({density:.2f} per 100, "
            f"needs {minimum:.2f}). Nothing joins one sentence to the next, so the "
            "narration is a list of facts and the viewer has to supply the reasoning.",
        )
    ]
