# Memory recall benchmark

- Date: 2026-10-01 11:27 · model `nomic-embed-text` on the CPU · 34 ms per message (warm)
- Seeded memory: 20 facts · 21 messages that need one, 4 that need none

| Recall@1 | Recall@3 | Recall@5 (spec ≥ 0.8) |
|---|---|---|
| 0.95 | 0.95 | **1.00** |

## What the agent gets: top 3, score ≥ threshold, within 0.08 of the best

Extra facts = facts given to a message that needed a different one (some are related,
e.g. the advisor's email for 'who is my advisor?').

| Threshold | Right fact included | Unrelated messages given a fact | Extra facts, no margin | Extra facts, with margin |
|---|---|---|---|---|
| 0.45 | 20/21 | 4/4 | 43 | 3 |
| 0.50 | 20/21 | 1/4 | 36 | 3 |
| 0.55 (used) | 20/21 | 1/4 | 19 | 0 |
| 0.60 | 19/21 | 0/4 | 6 | 0 |
| 0.65 | 16/21 | 0/4 | 2 | 0 |

## Per message (top 3 scores)

| Message | Needs | Rank | Top 3 |
|---|---|---|---|
| who is my advisor? | advisor | 1 | advisor 0.81, advisor-email 0.72, landlord 0.57 |
| what's my advisor's email address? | advisor-email | 1 | advisor-email 0.81, advisor 0.72, thesis 0.57 |
| email my advisor about the deadline | advisor-email | 1 | advisor-email 0.68, advisor 0.60, capstone 0.58 |
| can I eat a peanut butter cookie? | peanuts | 1 | peanuts 0.58, study 0.47, coffee 0.45 |
| when is my sister's birthday? | sister | 1 | sister 0.80, rent 0.53, capstone 0.52 |
| where do I park at school? | parking | 1 | parking 0.75, bus 0.55, dentist 0.52 |
| what's my student ID? | student-no | 1 | student-no 0.71, landlord 0.58, advisor-email 0.56 |
| when does my capstone group meet? | capstone | 1 | capstone 0.89, advisor-email 0.53, thesis 0.53 |
| when does my gym membership renew? | gym | 1 | gym 0.90, rent 0.54, capstone 0.53 |
| which bus do I take to campus? | bus | 1 | bus 0.81, parking 0.61, advisor-email 0.54 |
| what's my mom's number? | mom-phone | 1 | mom-phone 0.83, student-no 0.58, advisor-email 0.55 |
| when do I like to study? | study | 1 | study 0.75, capstone 0.60, job 0.57 |
| what laptop do I have? | laptop | 1 | laptop 0.80, landlord 0.59, vegetarian 0.59 |
| who's my landlord? | landlord | 1 | landlord 0.79, rent 0.57, advisor-email 0.57 |
| when is my rent due? | rent | 1 | rent 0.86, landlord 0.62, gym 0.58 |
| order my usual coffee | coffee | 1 | coffee 0.62, dentist 0.48, capstone 0.46 |
| am I working this weekend? | job | 1 | job 0.63, capstone 0.54, thesis 0.48 |
| book a dentist appointment | dentist | 1 | dentist 0.61, capstone 0.52, thesis 0.52 |
| what is my thesis about? | thesis | 1 | thesis 0.71, advisor 0.49, capstone 0.48 |
| suggest a dinner recipe for me | vegetarian | 4 | coffee 0.54, capstone 0.52, study 0.51 |
| who is my best friend? | friend | 1 | friend 0.80, advisor 0.55, landlord 0.52 |
| what is 2 plus 2? | - | - | friend 0.46, thesis 0.44, coffee 0.44 |
| tell me a joke | - | - | thesis 0.47, advisor-email 0.45, vegetarian 0.45 |
| what's the capital of Canada? | - | - | advisor-email 0.58, dentist 0.52, landlord 0.49 |
| how does photosynthesis work? | - | - | job 0.49, laptop 0.46, thesis 0.45 |
