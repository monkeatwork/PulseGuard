# PulseGuard, explained simply

## 1. The attack

An attacker already has someone's password. To log in they still need the
second factor, the "Approve?" push on the victim's phone. So they keep sending
pushes, maybe 20 in a few minutes, until the victim gets annoyed or confused
and taps **Approve**. This is called **MFA fatigue**.

A typical attack in our data looks like this on the victim's phone:

```
push -> Deny
push -> Deny
push -> Deny
push -> Deny
push -> Approve   <- attacker gets in
```

A normal login looks like this:

```
push -> Approve   (the user started the login themselves)
```

## 2. What PulseGuard looks at

Every time the user answers a push, PulseGuard looks at the session so far
(all pushes with no gap longer than 60 minutes) and computes about 19 numbers
("features"). They fall into two groups.

**How often pushes arrive (frequency):**
- how many pushes, how close together, how long the burst lasts
- is it the middle of the night, a new country, a new device?

**How the person reacts (response behaviour):**
- how many times in a row they pressed **Deny**
- did they deny, deny, deny and then approve?
- how fast they answered compared with their own usual speed
- whether their answers get faster and faster (the "reflex tap" idea)

## 3. Is it a model or hard-coded rules?

**It is a real trained model, not hard-coded rules.** Nobody wrote
"if denials >= 2 then alert". It has three parts, and their scores are
blended into one number from 0 to 1:

| Part | What it is | Weight in final score |
|---|---|---|
| Stage A | Simple statistics: "how unusual is this for this user?" | 10% |
| Stage B | XGBoost, a set of learned decision trees | 85% |
| Stage C | GRU, a small neural network that reads the pushes in order | 5% |

If the blended score goes over **0.67**, PulseGuard raises an alert and blocks the
approval, so the user has to do a stronger check instead.

The weights and the 0.67 cut-off were chosen automatically on a validation set
of users. The test users were never seen during training.

## 4. So how does it catch 99% with almost no false alarms?

We asked the trained model what it actually relies on. Here is Stage B's
answer (share of its decisions explained by each feature):

| Feature | Share |
|---|---|
| `deny_run_length` (denials in a row) | **84%** |
| whether there is an approval it can compare to the user's normal speed | 14% |
| new country | 2% |
| everything else, including the "getting faster" slope | ~0% |

So the model **learned by itself** that one thing almost perfectly separates
attacks from normal logins in our data: **two or more denials in a row**.

- 99.2% of attacks contain that pattern, because the victim denies a few times
  before giving in.
- **0 of 10,012** normal sessions contain it, because the data generator never
  makes a normal user deny twice in a row.

With a clue that clean, any learner gets about 99% recall and about 0.1%
false positives.

**The honest consequence:** a one-line hand-written rule ("alert on 2 denials in
a row") scores about the same: 99.5% caught, 0 false alarms. A plain logistic
regression does too. So on this dataset the model isn't doing anything a simple
rule can't. It just found that rule by itself.

## 5. What about the "reflex tap" speed idea?

That was supposed to be the main contribution: tired people answer faster and
faster. We tested it by generating data where attack victims answer at
**exactly the same speed as normal users** (no speed clue at all). PulseGuard
still caught 99.5%. So speed is not what makes it work here.

Speed only started to help when we made the data harder, by letting 10% of
normal busy users also press Deny a few times in a row:

| Detector | Normal users wrongly flagged |
|---|---|
| "2 denials in a row" rule | 42% (useless) |
| Elastic's rule | 42% |
| PulseGuard, no speed clue in the data | 3.9% |
| PulseGuard, with the speed clue | **0.8%** |

That is the one place where reaction speed clearly adds something. It holds
over 5 random seeds: the 95% ranges are 3.1–4.7% and 0.2–1.5%, so they don't
overlap.

## 6. Compared with what companies use today

| Detector | Attacks caught | Normal users wrongly flagged |
|---|---|---|
| Splunk rule (more than 9 pushes in 10 min) | 32% | 0% |
| Elastic rule (2 denials then an approval in 10 min) | 62% | 0.2% |
| **PulseGuard** | **99.9%** | **0.12%** |

The Splunk rule misses slow attacks. The Elastic rule fires only after the
approval, which is too late to block it, and it misses attacks spread over
more than 10 minutes.

## 7. Known weaknesses

- **Very slow attackers beat PulseGuard alone.** If pushes are sent more than
  1 hour apart, every push starts a new session, so PulseGuard never sees a run
  of denials. **Fix (built):** a second check counts, per user and across
  sessions, denials that were never followed by an approval within 10 minutes.
  It alerts at 3 of them within 7 days. Normal users who deny usually approve a
  retry within minutes, so those denials don't count.
  - PulseGuard + this check catches **100%** of attacks paced 2–4 hours apart,
    and 75% when the attacker uses a lure (the lure can end the attack after
    only 1–2 denials).
  - Users never attacked who get flagged: at most **0.2%**, even when we add
    a stray unanswered denial on 30% of their active days.
  - Not wired into the live service yet (needs Redis + Docker).
- **The data is synthetic.** Normal logins come from a real dataset (Wiefling
  RBA), but the attacks, the Deny/Approve choices and the reaction times are
  generated. Nobody has measured how real tired users behave; that needs a
  user study.
- **The "2 denials" shortcut** is partly a property of the generator. Real
  users sometimes do deny twice (a mis-tap, a login they didn't start). That is
  why the "harder data" test in section 5 matters.

## 8. Things that hold up

- It never locks the real user out, in all 72 attack settings tested.
- It does not depend on getting the exact fatigue pattern right: a model
  trained on one pattern still caught at least 99.4% on others.
- Results are averaged over 5 random seeds with 95% confidence intervals, and
  users are split train/test **by person**, so no user is in both.

## One-line summary

PulseGuard is a trained model that beats the industry rules by a wide margin,
but on this benchmark it wins because it notices repeated denials, not
because it reads reaction speed. Reaction speed helps only once repeated
denials stop being a giveaway.
