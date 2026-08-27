# Benchmark reference

`water_reclamation.txt` is a reconstruction of the narration from a Korean
architecture Short (@신비한_건축사전_1, "서울 사람들이 하루에 버린 물이 전부
모이는 곳"), supplied by the project owner as the quality target.

It is a fixture, not a test input: the checks in `quality/` are calibrated
against it, so its measured properties are the thresholds. Measured with
`scripts/measure_narration.py`:

| metric (per 100 chars) | benchmark | pipeline output at the time |
|---|---|---|
| deictic reference ("것들", "그 상태") | 0.16 | 1.92 |
| causal connective (그래서/되면/하지만/이에) | 0.97 | 0.00 |
| numerals | 0.81 | 0.00 |
| named entities | 6 distinct | 0 |
| mean sentence length | 44 chars | 22 chars |

## What the reference does that the pipeline did not

1. **Every sentence has a real grammatical subject.** 물, 오염물질, 미생물,
   산소, 서울시, 중랑물재생센터. The pipeline wrote "것들" instead.
2. **It pre-empts the naive answer.** "단순한 체로는 제거하기 어렵습니다" tells
   the viewer why the obvious solution fails, which turns a list of steps into
   an argument.
3. **It anchors with numbers and names.** 1976년, 100만 톤, 축구장 100개,
   150 → 20.
4. **It turns to people.** 주민들이 가까이 두기를 꺼리는 시설 → 지하화 → 공원.
   The pipeline's beat purposes had no slot for this.
5. **It closes by reframing.** "미생물에게 정화를 맡기는 물 공장."
6. **It is comprehensible with the eyes closed.** This is the property the
   pipeline lacked most: its narration only made sense against the picture.

## Why the old writer prompt could not produce this

The prompt's stated highest-priority rule was "can this be shown in one shot?
If you cannot fill in visual_payoff, the sentence does not belong in a video
script." Applied to this reference it deletes 6 of its 9 core sentences,
leaving only the middle mechanism description -- no context, no stakes, no
numbers, no names, no close. That is exactly the shape the pipeline produced.

## Visual language (from stills of the same Short)

Worth recording because it is not what the pipeline was aiming at:

- **Stylised architectural CGI, deliberately not photoreal.** An isometric
  cutaway reads as an explanatory diagram, so it does not assert "this is a
  photograph of the real thing" the way photoreal footage does.
- **The detail comes from motion-graphic overlays, not the renderer**:
  engineering-style dimension lines ("10mm" with end brackets), red callout
  boxes ("수백만t"), target reticles. No image model produces these; they are
  composited afterwards.
- **Two registers**: dark, wet, industrial for interiors; bright, clean,
  sectional for the architectural views.
