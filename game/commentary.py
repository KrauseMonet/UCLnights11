"""One line of commentary for each goal (C61): how it came (game.goal_kinds) and what it
meant at that moment.

A line is how the goal was made ("Whipped in from the flank"), how it was finished ("met
with a bullet header"), and a short tag for the moment ("Level at the death!").
**The tag knows only the match so far**: the score before and after, the scorer's goals
in this match, the minute, whether he came off the bench. It never says "the winner" or
"the decider", which would need knowing nothing else is scored, and in a match let out in
pieces (C52, C60) that would give the ending away. Nor does it say anything from a rating.

The words are written for this site, none taken from a broadcast. Each goal picks its
words from a stream of its own (named as its kind's is, with another prefix, so editing a
phrase never moves a kind), and a phrase already used earlier in the match is skipped,
so a match never repeats itself; both depend only on goals before it.
"""

from __future__ import annotations

import random
from typing import Sequence

from game.goal_kinds import Kind, goal_name
from game.match import Goal

# The words name nobody: the scorer and assister are named right beside the line (the goal
# burst, the feed, a result row), and saying them again doubled its length.

# How an assisted goal was made.
MADE = {
    "pass": ["Threaded through", "A slide-rule pass", "Laid off on the edge", "A slick one-two",
             "Played into the path"],
    "cross": ["Whipped in from the flank", "Hung up at the far post", "Crossed from the byline",
              "Swung in from wide"],
    "corner": ["Corner swung in", "From the corner", "A near-post corner", "Corner curled in"],
    "header": ["Nodded down", "Headed back across goal", "Flicked on with the head"],
    "rebound": ["Parried by the keeper", "Off the post", "Blocked, falls kindly", "Pushed out by the keeper"],
    "free_kick": ["Free kick floated in", "Free kick whipped in", "A set piece into the box"],
}

# How it was finished, after a clause from MADE; {foot} is "left" or "right".
FINISH = {
    "header": ["and it's headed home", "met with a bullet header", "glanced into the far corner",
               "nodded past the keeper"],
    "foot": ["slotted home with the {foot}", "drilled in, {foot}-footed", "curled into the far corner",
             "fired past the keeper with the {foot}"],
    "tap_in": ["tapped in from two yards", "an easy tap-in", "poked home from close range", "impossible to miss"],
    "volley": ["smashed in on the volley", "hit first time, on the volley", "a sweet half-volley",
               "volleyed into the roof of the net"],
    "long_range": ["a {foot}-footed rocket from 25 yards", "struck from distance, and in it goes",
                   "from miles out! What a strike", "a thunderbolt from range"],
    "solo_run": ["then past two men and finished", "a dance through the defence, and in",
                 "a slalom, and a {foot}-footed finish"],
}

# A goal nobody made, whole.
ALONE = {
    "penalty": ["Sends the keeper the wrong way from the spot", "From the spot. No mistake",
                "Penalty smashed in", "Penalty rolled into the corner, ice cold"],
    "free_kick": ["Free kick curled over the wall", "Free kick bent into the top corner",
                  "Free kick hammered through the wall", "Free kick whipped in. The keeper never moves"],
    "header": ["A header from the scramble", "Nodded in from a loose ball", "Headed in as the clearance drops"],
    "foot": ["Pounces on a loose ball, {foot}-footed finish", "Wins it back and scores", "Driven in with the {foot}"],
    "tap_in": ["First to react, and tapped in", "First to the loose ball"],
    "volley": ["The clearance volleyed straight back in", "A loose ball, met on the volley"],
    "long_range": ["Picks it up and lets fly with the {foot}", "From 30 yards. Unstoppable",
                   "Tried from range, and it flies in"],
    "solo_run": ["Picks it up on halfway and runs through on goal", "Slaloms past three defenders and scores",
                 "Does it all alone"],
}

# The moment, by what it was when the goal went in (``moment``); {N} a number word.
TAG = {
    "hat_trick": ["Hat-trick!", "That's three! Hat-trick.", "Match ball time. Hat-trick!"],
    "haul": ["That's {N}! Unstoppable.", "{N} of them now. Ridiculous."],
    "comeback": ["What a turnaround!", "Behind earlier, in front now!", "The comeback is on!"],
    "late_level": ["Level at the death!", "Late, late drama. All square!", "Rescued, right at the end!"],
    "late_ahead": ["Late, late drama!", "Ahead at the death!", "Scenes! That could be huge."],
    "et_level": ["Level in extra time!", "All square in extra time!"],
    "et_ahead": ["In front in extra time!", "Extra-time drama!", "Extra time, and this!"],
    "level": ["All square.", "Level!", "Game on.", "Parity restored."],
    "early": ["What a start!", "Barely kicked off!", "Off to a flyer!"],
    "opener": ["The deadlock is broken.", "First blood.", "The opener!", "And the breakthrough comes."],
    "ahead": ["In front!", "Nose in front.", "That's the lead.", "They lead!"],
    "brace": ["A brace!", "Double trouble.", "Two and counting."],
    "bench": ["Off the bench and straight in!", "What a change that was!", "Super sub!"],
    "one_back": ["One back.", "A lifeline!", "Game on? One back.", "Hope!"],
    "clear": ["Two clear.", "Breathing room.", "Daylight.", "That should settle the nerves."],
    "rout": ["This is a rout.", "Rampant!", "Cruising.", "It's raining goals."],
}

WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]


def moment(g: Goal, before: tuple[int, int], trailed: bool, scored: int, from_bench: bool) -> str:
    """What the goal was when it went in. ``before`` is the score before it, ``trailed``
    whether the scoring side had been behind earlier in the match, ``scored`` the scorer's
    goals in the match counting this one."""
    mine, theirs = before[g.side], before[1 - g.side]
    after = mine + 1
    late = 85 <= g.minute <= 90 or g.minute >= 115
    if scored >= 4:
        return "haul"
    if scored == 3:
        return "hat_trick"
    if trailed and mine <= theirs < after:
        return "comeback"
    if after == theirs or (mine == theirs and after > theirs):
        level = after == theirs
        if late:
            return "late_level" if level else "late_ahead"
        if g.minute > 90:
            return "et_level" if level else "et_ahead"
        if level:
            return "level"
        if mine == 0:
            return "early" if g.minute <= 5 else "opener"
        return "ahead"
    if scored == 2:
        return "brace"
    if from_bench:
        return "bench"
    if after < theirs:
        return "one_back"
    return "rout" if after - theirs >= 3 else "clear"


def _pick(rng: random.Random, used: dict[str, set[int]], key: str, options: list[str]) -> str:
    """A phrase not yet used in this match, if there is one left."""
    start = rng.randrange(len(options))
    seen = used.setdefault(key, set())
    for step in range(len(options)):
        i = (start + step) % len(options)
        if i not in seen:
            break
    else:
        i = start
    seen.add(i)
    return options[i]


def line_of(rng: random.Random, used: dict[str, set[int]], g: Goal, k: Kind, tag: str, scored: int) -> str:
    words = {"foot": k.foot or "", "N": WORDS[scored].capitalize() if scored < len(WORDS) else str(scored)}
    finish = k.flavour or k.finish
    if k.made is None:
        body = _pick(rng, used, "alone." + finish, ALONE[finish])
    else:
        body = (_pick(rng, used, "made." + k.made, MADE[k.made]) + ", "
                + _pick(rng, used, "finish." + finish, FINISH[finish]))
    return (body + ". " + _pick(rng, used, "tag." + tag, TAG[tag])).format(**words)


def lines(match: str, goals: Sequence[Goal], kinds: Sequence[Kind],
          starters: tuple[set[str], set[str]]) -> list[str]:
    """Each goal's line, in the order given. ``starters`` holds each side's starting eleven
    by person, so a goal from the bench is known as one."""
    out, score, used = [], [0, 0], {}
    trailed, scored = [False, False], {}
    for g, k in zip(goals, kinds):
        before = (score[0], score[1])
        rng = random.Random("commentary|" + goal_name(match, g, before))
        key = (g.side, g.scorer.id)
        scored[key] = scored.get(key, 0) + 1
        tag = moment(g, before, trailed[g.side], scored[key], g.scorer.id not in starters[g.side])
        out.append(line_of(rng, used, g, k, tag, scored[key]))
        score[g.side] += 1
        for s in (0, 1):
            trailed[s] = trailed[s] or score[s] < score[1 - s]
    return out
