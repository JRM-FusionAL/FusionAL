# OpenRouter Fusion Stress Test Suite

## Test 1: Time-Sensitive Synthesis (Full Stack — Web + Reasoning + Synthesis)

```
Today is June 25, 2026. Find the three most significant AI safety policy
developments from the last 7 days. For each:

1. Summarize the key change in one sentence
2. Identify who benefits most (companies, researchers, public, regulators)
3. Predict the second-order effect on open-source AI development

Be specific — name the policy, the date, the actors. No generic statements.
If you can't find something from the last 7 days, say so explicitly rather
than padding with older news.
```

**Scoring:**
- 3 pts: All three events are real and from the correct date range
- 3 pts: Second-order effects are specific and non-obvious
- 2 pts: No hallucinated events or actors
- 2 pts: Synthesis adds value beyond what a single model would produce

---

## Test 2: Adversarial Debugging (Pure Reasoning)

```
Here's a Python async function that intermittently deadlocks in production
but has no logging. The code looks correct at first glance.

```python
import asyncio

async def process_queue(queue: asyncio.Queue, results: list):
    while True:
        item = await queue.get()
        if item is None:
            break
        result = await transform(item)
        results.append(result)
        queue.task_done()

async def main():
    queue = asyncio.Queue()
    results = []
    
    # Spawn workers
    workers = [asyncio.create_task(process_queue(queue, results)) for _ in range(3)]
    
    # Feed data
    for i in range(100):
        await queue.put(i)
    
    # Signal stop
    for _ in range(3):
        await queue.put(None)
    
    await queue.join()
    
    for w in workers:
        w.cancel()
    
    return results
```

Walk through it systematically:
1. What are ALL the possible deadlock scenarios?
2. How would you reproduce each one deterministically?
3. What's the minimal fix?

Be exhaustive. The obvious answer is not the only one.
```

**Scoring:**
- 4 pts: Identifies the `task_done()` / `join()` race with `cancel()`
- 3 pts: Identifies the `await` after `None` sentinel as a hang vector
- 2 pts: Provides a deterministic reproduction (not "add logging and hope")
- 1 pt: Minimal fix is actually minimal (not a full rewrite)

---

## Test 3: Ethical Architecture (Nuanced Judgment)

```
I'm building a health app that shares anonymized patient data with medical
researchers. A patient advocacy group says this violates trust even with
consent. A researcher says blocking it slows critical disease research.

Give me ONE concrete architecture decision — not both-sides-ism. Then defend
it against the strongest counterargument. Your answer must be implementable
in under 2 weeks by a 3-person team with a $15k budget constraint.
```

**Scoring:**
- 3 pts: Decision is actually concrete (specific tech, specific flow)
- 3 pts: Counterargument is the STRONGEST one, not a strawman
- 2 pts: Defense is substantive, not hand-wavy
- 2 pts: Respects the budget/time constraint

---

## Test 4: Formal Logic Trap (Pure Reasoning)

```
Consider these three sentences:

S1: "If S2 is true, then S3 is false."
S2: "If S3 is false, then S1 is true."  
S3: "S1 is false."

Is there a consistent truth assignment? If not, what's the MINIMAL change
needed to make it consistent? This is NOT a trick question — there's a
real, verifiable answer. Show your work step by step.
```

**Scoring:**
- 4 pts: Correctly identifies the paradox (or lack thereof)
- 3 pts: Shows the truth table or formal derivation
- 2 pts: Minimal change is actually minimal (one word, one operator)
- 1 pt: Doesn't give up with "it's just a paradox" without proving it

---

## How to Run

1. Go to https://openrouter.ai/chat
2. Select model: `openrouter/fusion`
3. Paste each test separately
4. Save the responses
5. Score using the rubric above

## What to Look For

**Signs Fusion is working well:**
- Different panel members contribute different insights
- The synthesis actually adds value beyond "here are 3 opinions"
- Web results are correctly attributed and dated
- No single model's hallucination dominates

**Signs it's just routing to one model:**
- Response reads like a single voice
- No genuine disagreement in the deliberation
- One model's known failure mode shows up uncorrected
