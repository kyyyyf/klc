# Предложения по обновлению агентских промптов

Дата: 2026-06-11. Ветка: `feature/KLC-022-jira-pull`.

Документ — только **предложения** (что/где/на что менять и зачем). Ничего не
применяю до твоего подтверждения.

## Цели (из задачи)

0. **Design учитывает все зависимости.** Сейчас blast-radius (кто зависит от
   меняемых модулей) проверяется только на review (`review/architecture.md`
   читает `depgraph.json`), а `design.md` — нет. Поздно.
1. **Усиление детерминизма имплементации.** Planning/design (фазы на более
   дорогих моделях) должны выдавать короткий исполнимый roadmap: чёткие шаги →
   commit, TDD «failing test до кода». Существующие детерминированные правила не
   убираем — усиливаем. Учитываем разные треки.
2. **Стоп при необходимости сменить модель** — если работаешь внутри Claude
   Code / Codex CLI и можешь переключиться сам.
3. **Review не должен проходить «халявно».** Внутри упомянутых приложений —
   спрашивать, гонять ли полную версию review. Учитываем треки.

## Что я взял из `codex_prompts_improvements.md`, что поправил

| Предложение codex | Вердикт |
|---|---|
| §2 контракт шага `impl-plan.md` (RED/GREEN/VERIFY/COMMIT) | **Принять**, доработать формулировку трек-форм |
| §5 S-track `impl-plan.md` из test-planner | **Принять** — gap реальный (см. ниже) |
| §6 XS test-first | **Принять** |
| §7 impl.md потребляет roadmap | **Принять** |
| §9–§11 review depth confirmation | **Принять**, выровнять с реальными фазами/треками |
| §1 model handoff guard | **Принять**, ужать список файлов и детект |
| §3–§4 правка `.j2` шаблонов | **Понизить приоритет** — шаблоны **не рендерятся** кодом (см. факт A); это документация-контракт, не runtime |
| §8 RED/GREEN в step-card | **Принять, но проще** — парсер уже пробрасывает эти поля в `step_description` без правок кода (факт B) |
| §12 `scripts/review.py` `KLC_FORCE_FULL_REVIEW` | **Принять как 2-й этап** (код, не промпт) |
| §13 комментарий в `models.yml` | **Принять** |
| §15 typo `wheter`→`whether`, поля `review_depth` | **Принять** |
| (нет у codex) **Dependency impact в design** | **Добавляю** — это твоя цель 0 |

### Факты, проверенные по коду (важны для приоритета)

- **Факт A.** `core/templates/impl-plan.md.j2` и `impl-plan-short.md.j2` не
  рендерятся ни одним `.py` (grep по `core/`, `scripts/` пуст). `impl-plan.md`
  пишет сам design-агент как markdown. В `docs/process-artifacts.md` они
  заявлены как источник рендера — фактически это контракт-образец. → правка
  шаблонов полезна для консистентности, но **не** меняет поведение runtime.
- **Факт B.** `core/skills/artefacts.py:_extract_impl_step` парсит из шага
  только `**Affected files**`, `**Expected tests**`, `**Rollback**`; `desc`
  получается как «тело минус эти три секции». Значит новые поля
  `**RED/GREEN/VERIFY/COMMIT**` попадут в `step_description` step-карточки
  **автоматически**, без правки парсера. Дискретными полями они не станут, но
  агент их увидит.
- **Факт C (gap).** `build` (треки S/M/L) во входах требует `impl-plan.md`
  (`phases.yml:213`), и `artefacts.py` парсит его для step-карточек. Но `design`
  — только треки M/L. Для **S** `impl-plan.md` никто не создаёт. Это и есть дыра,
  которую закрывает §5 codex.

---

## A. `core/agents/design.md` — roadmap-контракт шага (цель 1)

### A1. Заменить раздел `### 3. impl-plan.md`

**Было** (строки 61–72):

```markdown
### 3. `impl-plan.md`

Step list with IDs `[step-1]`, `[step-2]`, ... — each step is one
logical commit. Per step:

- Description
- Affected files
- Expected tests (from test-plan.md)
- Rollback note (only if the step is risky)

Short form for S track (≤ 10 lines, single step). Full form
otherwise.
```

**Стало:**

```markdown
### 3. `impl-plan.md`

Write an executable roadmap for the Build phase. Audience: the test
agent, impl agent, verifier, and human operator. It must be short and
runnable **without re-designing the ticket**.

Step list with IDs `step-1`, `step-2`, ... — each step is exactly one
logical commit. Each step MUST contain, in this order:

- **Goal**: one sentence — the behaviour or structural change.
- **RED**: the failing test to write first. If the step adds or changes
  behaviour this is mandatory and must cite a test row from
  `test-plan.md`. If the step is wiring/docs/config only, write
  `RED: not applicable` + a one-sentence reason.
- **GREEN**: the smallest code change expected to pass RED.
- **VERIFY**: the exact targeted test command or suite/case name.
- **COMMIT**: proposed commit subject, prefixed `<ticket-key> step-N:`.
- **Affected files**: concrete paths. Unknown paths require an
  `[!ASSUMPTION]` or `[!QUESTION]`, never a guess.
- **Depends on**: earlier `step-K` ids this step needs, or `none`.
- **Rollback note**: only if the step is risky.

Track-specific shape (do not drop steps to hit a number — split or merge
honestly):

- **S**: Design normally does not run. If invoked manually for S, 1–3
  steps, prefer the short form.
- **M**: aim for 3–5 steps. Risky API/schema/boundary work goes **first**.
- **L**: 5–9 steps grouped by milestone; each milestone still decomposes
  into one-commit steps. No vague "big refactor" step.

**TDD rule:** for any behaviour-changing step, the RED test is written
and confirmed failing **before** its implementation code.
```

**Что достигается:** design перестаёт описывать только архитектуру и отдаёт Build
конкретный маршрут с TDD/commit-дисциплиной; формы по трекам сохранены и явные.
`Depends on` делает порядок шагов детерминированным.

### A2. Дополнить `YAGNI validation before writing`

**После** строки (87):

```markdown
- Dependencies are linear — no step requires output from a later step.
```

**добавить:**

```markdown
- Every behaviour-changing step has an explicit RED test and a VERIFY
  command; wiring-only steps say `RED: not applicable` with a reason.
- Every step has a proposed COMMIT subject and maps to exactly one
  logical commit unless the step explicitly states why not.
- Every step's `Depends on` lists only earlier step ids (no forward
  references).
```

**Что достигается:** YAGNI-гейт теперь и проверяет полноту roadmap-контракта, не
ослабляя старые проверки.

---

## B. `core/agents/design.md` — учёт зависимостей (цель 0) — НОВОЕ

Этого нет у codex. Цель: чтобы design **до** выбора опции смотрел реальный граф
зависимостей и blast-radius, а не оставлял это review.

### B1. Добавить в `## Inputs (from design-context/)`

**После** строки `- 20-related-adrs.md (optional)`:

```markdown
- `.klc/index/depgraph.json` — `import_graphs.<lang>` (authoritative
  module/file dependency edges). Read on demand.
- `.klc/index/modules.json` — module → path map for resolving
  `affected_modules`.
```

### B2. Добавить новый шаг `### 1a. Dependency impact analysis` (перед `### 1. Generate options`)

```markdown
### 1a. Dependency impact analysis

Before generating options, compute the blast radius of the change so it
can be reflected in every option's `Affected files` / `Risks` instead of
being discovered at review.

1. For each module in `meta.json.affected_modules`, read
   `depgraph.import_graphs.<lang>.edges` and list:
   - **downstream** — modules/files this one imports (what the change
     may break that it relies on);
   - **upstream (dependents)** — modules/files that import this one
     (who breaks if its public API changes).
2. Verify the touched public symbols with LSP `findReferences` to
   confirm the real call sites, not just module-level edges.
3. Record findings in `design/options.md` under a short
   `## Dependency impact` section:
   - dependents that must keep compiling / passing tests,
   - any edge a candidate option would **add or invert** (new coupling),
   - cycles the change would create.

Rules:
- An option that adds a cross-module edge not present in `depgraph` or
  inverts an existing one MUST flag it in its `Risks` and trigger the
  ADR check (cross-module boundary crossed).
- If a dependent is outside `affected_modules`, do not silently expand
  scope — raise `[!QUESTION]` (extend ticket?) or `[!CONFLICT]`.
- If `depgraph.json` is missing or has no graph for the language, write
  `dependency-impact: unavailable (<reason>)` and fall back to LSP
  `findReferences` on the touched symbols; do not skip silently.
```

### B3. Дополнить ADR trigger (`### 2. ADR trigger`)

**После** `- cross-module boundary crossed` добавить:

```markdown
- a new dependency edge added or an existing edge inverted (per the
  dependency-impact analysis)
```

**Что достигается:** зависимости перестают «оставаться» необработанными — каждая
опция явно показывает downstream/upstream impact и новые рёбра графа; review
больше не первое место, где всплывает blast-radius.

---

## C. `core/agents/test-planner.md` — S-track создаёт короткий `impl-plan.md` (Факт C)

### C1. Добавить в `## Role` (после описания двух режимов, после строки 11)

```markdown
For **S-track** tickets there is no Design phase, yet Build still
requires `impl-plan.md`. In acceptance mode you therefore also produce a
**short** `impl-plan.md` so Build receives step cards with TDD and commit
boundaries. Do not do architecture design — derive the minimal roadmap
from `spec.md` and the acceptance tests only.
```

### C2. Добавить в конец `### Phase 2 — acceptance mode` (после блока "Rules for acceptance mode")

```markdown
**S-track only — also write `impl-plan.md` (short form):**

- 1–3 steps, each exactly one logical commit.
- Each behaviour-changing step has `Goal`, `RED`, `GREEN`, `VERIFY`,
  `COMMIT` (prefixed `<KEY> step-N:`), concrete `Affected files`, and
  `Depends on`.
- Step headers use the `## step-N — <title>` form so the Build phase can
  parse them.
- If the work cannot be planned without design trade-offs, do NOT invent
  a plan — emit `[!QUESTION blocks=acceptance-test-plan]` recommending an
  upgrade to M.

Do **not** create `impl-plan.md` for XS (XS uses `xs-fasttrack.md`).
Do **not** overwrite a Design-produced `impl-plan.md` on M/L.
```

> Примечание: добавить `impl-plan.md` в `outputs` фазы `acceptance-test-plan` в
> `phases.yml` **нельзя напрямую** — фаза общая для S/M/L, а на M/L план пишет
> Design. Поэтому контроль остаётся на уровне промпта (трек-условие), либо
> отдельным 2-м этапом сделать output условным в `artefacts.py`. См. раздел I.

**Что достигается:** закрывается Факт C — у S появляется детерминированный
roadmap без запуска тяжёлого Design.

---

## D. `core/agents/xs-fasttrack.md` — test-first без превращения в S (цель 1)

### D1. Заменить `### 4. Write the test` (строки 73–82)

**Было:**

```markdown
### 4. Write the test

Write at least one test that would have failed before your change and
passes after. Place it in the project's existing test directory
following the conventions in CLAUDE.md.

The test must be runnable with the command in CLAUDE.md's "Test run"
section. If that section is absent, use the command in `meta.json`
(field `test_cmd`).
```

**Стало:**

```markdown
### 4. Write the RED test first

Write at least one test **before** the fix. For bug tickets it must be a
regression test reproducing the bug; for feature/content/config tickets
it must cover the acceptance criterion the XS change claims to satisfy.

Run the targeted test before implementation and confirm it is RED. If it
passes before the fix, stop and emit `[!QUESTION]` — the test does not
prove the change, so reorder: test → confirm red → fix → green.

Place it in the project's existing test directory per CLAUDE.md
conventions. It must be runnable with the command in CLAUDE.md's
"Test run" section, or `meta.json` (`test_cmd`) if that section is absent.
```

> Также переставить местами шаги: текущий порядок `3. Write the fix` → `4. test`
> противоречит test-first. Рекомендую поменять заголовки на `3. Write the RED
> test first` и `4. Write the fix`, либо явно оговорить в шаге 3, что код пишется
> только после красного теста из шага 4. Минимальный вариант — оставить нумерацию,
> но в начале `### 3. Write the fix` добавить строку: «Do this only after the RED
> test from step 4 exists and fails.»

**Что достигается:** XS остаётся fast-track, но «fix-first, test-later» запрещён.

---

## E. `core/agents/impl.md` — жёстче потреблять roadmap (цель 1)

### E1. Дополнить `## Plan validation (before writing any code)` → блок `Completeness`

**После** последнего пункта `Completeness` (строки 87–92) добавить новый блок:

```markdown
**Roadmap contract:**
- [ ] Current step exposes Goal / RED / GREEN / VERIFY / COMMIT (or is a
      legacy short-form step lacking them — then treat its description as
      Goal and derive RED from `test-plan.md`).
- [ ] If the step changes behaviour, the RED test already exists and is
      known to fail before any code change.
- [ ] The planned commit subject maps to **this step only**.
- [ ] `Depends on` steps are all already green.
```

### E2. Дополнить `## Step bookkeeping`

**После** строки `For every step you complete:` (строка 95) добавить первым пунктом:

```markdown
- Commit only after the step is green, using the step's `COMMIT`
  subject when present. If you cannot commit in this environment, record
  the exact commit subject + changed files in `build-log.md`.
```

**Что достигается:** impl-агент перестаёт трактовать план как необязательную
подсказку; при неполном roadmap останавливается до правок (как уже требует блок
`When to stop and ask`).

---

## F. Шаблоны — синхронизировать как контракт (низкий приоритет — Факт A/B)

> Эти шаблоны **не рендерятся кодом**, поэтому правки тут не меняют runtime, но
> держат образец в согласии с новым контрактом и с `docs/process-artifacts.md`.

### F1. `core/templates/impl-plan.md.j2` — тело шага

**Заменить** блок строк 13–28 (от `{{ step.description }}` до `{% endif %}`) на:

```markdown
**Goal**: {{ step.goal or step.description }}

**RED**: {{ step.red or "behaviour-changing steps require a failing test before code" }}

**GREEN**: {{ step.green or "smallest code change to pass RED" }}

**VERIFY**: `{{ step.verify or "see test-plan.md" }}`

**COMMIT**: `{{ ticket }} step-{{ loop.index }}: {{ step.commit_subject or step.title }}`

**Affected files**:
{% for f in step.files %}
- `{{ f }}`
{% endfor %}

**Expected tests**:
{% for t in step.tests or [] %}
- `{{ t }}`
{% endfor %}

**Depends on**: {{ step.depends_on or "none" }}
{% if step.rollback %}

**Rollback**: {{ step.rollback }}
{% endif %}
```

### F2. `core/templates/impl-plan-short.md.j2` — синхронизировать (S-форма)

**Заменить** строки 9–15 (от `## step-1` до `Test:`) на цикл с теми же полями
(Goal/RED/GREEN/VERIFY/COMMIT/Affected), что и в полном шаблоне, но компактно —
как в §4 codex.

### F3. `core/templates/impl-step.md.j2` — напоминание о контракте

**После** блока `**Expected tests**` (строка 30) добавить статический блок:

```markdown
### Roadmap contract (from impl-plan.md)

- **RED**: write/confirm the failing test before code.
- **GREEN**: smallest change to pass RED.
- **VERIFY**: run the step's targeted command before signalling success.
- **COMMIT**: one logical commit after green, using the step's subject.

If any of these are missing for a behaviour-changing step, stop and add
`[!QUESTION blocks=build]` to `impl-plan.md`; do not infer a new plan.
```

**Что достигается:** контракт виден сразу в карточке шага (а полные RED/GREEN
поля и так попадают в `step_description` — Факт B), без правки парсера.

### F4. `docs/process-artifacts.md` — честно описать роль шаблонов (Q3)

**Было** (строка 121):

```markdown
Rendered from `impl-plan.md.j2` (full) or `impl-plan-short.md.j2`.
```

**Стало:**

```markdown
Authored by the design agent (S: by the test-planner) to match the shape
in `impl-plan.md.j2` (full) / `impl-plan-short.md.j2`. These templates are
a **contract sample**, not a runtime renderer — no code renders them today.
```

**Что достигается:** документация перестаёт врать про «rendered from»; шаблон
закреплён как образец-контракт (решение Q3: вариант A, рендер не подключаем).

---

## G. Model handoff guard (цель 2) — схема «2+1»

> Решение по Q1/Q4: автодетекта модели в Codex CLI нет, поэтому guard в ручном
> режиме = «подтвердите модель». Чтобы не плодить вопросы на дешёвых фазах,
> применяем guard выборочно:
>
> - **Блокирующий** — только на heavy-reasoning фазах: `design.md`, `discovery.md`
>   (единственные, где ждётся Opus; запуск на Sonnet/Haiku бьёт по целям 0/1).
> - **Info-строка** (без вопроса) — `impl.md`, `xs-fasttrack.md`, `review.md`:
>   напоминание «переключись вниз на Sonnet», ошибка тут = переплата, не качество.
> - **Не трогаем** — `discovery-lite.md`, `review-lite.md`, `review/cheap.md`,
>   `test-planner.md`: дешёвые модели по умолчанию, вопрос был бы чистым шумом.

### G1. Блокирующий guard — вставить в `design.md` и `discovery.md`

Сразу после `## Inputs`:

````markdown
## Model handoff guard

This is a heavy-reasoning phase — it must run on the Opus-tier model.

1. Read `.klc/tickets/<KEY>/meta.json` → `track`.
2. Read `.klc/config/models.yml` if present, else `config/models.yml`.
3. Resolve role in order: `per_track.<track>.<phase>` → `phase_roles.<phase>`
   → `defaults`. Map role → `provider:model` via `roles`.
4. Detect the host model when possible (`KLC_MODEL_*` env, the Claude Code
   model indicator, this card's metadata).

- Model **detectable & mismatched** → **stop before modifying files**:
  ```text
  MODEL_SWITCH_REQUIRED <KEY> phase=<phase-id> track=<track> required_role=<role> required_model=<provider:model> current_model=<provider:model>
  ```
  Wait for the operator to switch and re-run this prompt.
- Model **not detectable** (e.g. Codex CLI) → print the required model
  once and ask the operator to confirm this session already uses it
  before continuing:
  ```text
  This phase expects <provider:model> (Opus-tier). Confirm this session is on it? [y/N]
  ```
- Unattended runner (`RUN_LOCAL_SUBAGENTS=1`) → do **not** ask; trust
  `KLC_MODEL_*` (the runner already picked the model from `models.yml`).
````

### G2. Info-строка — вставить в `impl.md`, `xs-fasttrack.md`, `review.md`

Сразу после `## Inputs` (короткий, **неблокирующий** блок):

````markdown
## Model note

This phase expects the coding-tier model, not Opus. Resolve it from
`models.yml` (`per_track.<track>.<phase>` → `phase_roles.<phase>` →
`defaults`) and, if you just came from a heavy-reasoning phase, switch
**down** before working. This is a cost note, not a gate — do not stop or
ask; just print one line if a downgrade is warranted:

```text
MODEL_NOTE <KEY> phase=<phase-id> expects=<provider:model> (downgrade from design/discovery Opus)
```
````

**Что достигается:** Opus гарантирован там, где он реально нужен (design/discovery);
на coding-фазах оператор видит ненавязчивое «пора вниз»; дешёвые фазы и runner не
получают лишних вопросов. Резолюция совпадает с порядком в `config/models.yml`.

> Эффективность: оба блока можно позже вынести в общий snippet и инклюдить при
> рендере `_prompt.md` (`artefacts.py`) — но это код-этап; для paste-only
> workflow надёжнее текст прямо в промптах.

---

## H. Review не «халявит» (цель 3)

### H1. `core/agents/review.md` — заменить строку в `## Role` (строки 6–7)

**Было:**

```markdown
Run a multi-agent code review of a change. Launch every sub-agent listed
by the active profile, aggregate their output, render a binary verdict. Stop and ask wheter to continue.
```

**Стало:**

```markdown
Run code review at the depth required by the ticket track and the cascade
signals. Launch the selected sub-agents, aggregate their output, render a
binary verdict. In manual Claude Code / Codex CLI workflows, explicitly
ask the operator before accepting a cheap/lite path when a full review is
available.
```

*(исправляет и опечатку `wheter`).*

### H2. `core/agents/review.md` — добавить `### 1a.` после `### 1. Resolve inputs`

```markdown
### 1a. Review-depth confirmation (manual app workflows)

Read `track` from `meta.json` when available. This prompt runs only on
S/M/L (XS uses `review-lite`). Policy:

- **S**: run cascade. If cascade selects the **cheap** path AND this is a
  manual Claude Code / Codex CLI session, stop and ask:
  `Cascade selected cheap review: <reason>. Run full multi-agent review instead? [y/N]`
- **M / L**: full multi-agent review is required. Do not downgrade to the
  cheap path in manual workflows unless the human explicitly overrides
  after seeing the cascade reason.

Unattended runner (`RUN_LOCAL_SUBAGENTS=1` + `REVIEW_RUNNER` set): do not
ask — follow `config/reviewers.yml` and record the cascade decision.

If the operator chooses full review, force the multi-agent path even when
cascade would allow cheap. Record `review_depth: cheap|full` and
`full_review_offered: true|false` in the report frontmatter.
```

### H3. `core/agents/review-lite.md` (XS) — добавить `### 1a.` после `### 1. Read the diff`

````markdown
### 1a. Full-review upgrade offer (manual app workflows)

If running manually in Claude Code / Codex CLI, inspect the diff shape
before writing the report. Stop and ask whether to run full review when
any of these hold:

- public API, auth, security, data persistence, migration, dependency
  manifest, or build-system file changed;
- more than 3 files changed;
- the change is not obviously covered by one targeted test;
- you cannot confidently classify the risk as XS after reading the diff.

If the operator declines → continue review-lite, set
`full_review_declined: true` in the report frontmatter.
If the operator accepts → emit and stop:

```text
FULL_REVIEW_REQUESTED <KEY>
```
````

### H4. `core/agents/review/cheap.md` — добавить после `## Inputs`

````markdown
## Manual full-review confirmation

If you are running this card manually in Claude Code / Codex CLI, do not
start reviewing until the operator confirms cheap review is acceptable
for this pass. Show the cascade reason from the job card if present. If
the operator asks for full review, emit and stop without a cheap verdict:

```text
FULL_REVIEW_REQUESTED <KEY>
```

Unattended runner mode: proceed without asking.
````

**Что достигается:** разные правила строгости по трекам (XS lite + escalation, S
cascade-confirm, M/L full); cheap-путь не проходит без видимого решения оператора;
CI/local runner остаётся неинтерактивным; ретроспектива получает `review_depth`.

---

## I. Поддержка кодом и конфигом (2-й этап, не промпты)

1. **`scripts/review.py`** — когда cascade выбрал cheap, а `RUN_LOCAL_SUBAGENTS`
   не задан, печатать в ACTION REQUIRED предложение запустить full и поддержать
   `KLC_FORCE_FULL_REVIEW=1` (как §12 codex). Подкрепляет H2/H4 на уровне CLI.
2. ~~**`core/skills/artefacts.py`** — сделать `impl-plan.md` обязательным output
   `acceptance-test-plan` при `track == S`.~~ **Решено (Q2): не делаем.** Закрываем
   Факт C только промптом (раздел C). Гейт остаётся возможной будущей задачей, если
   на практике агент будет забывать писать план.
3. **`config/models.yml`** — добавить над `phase_roles` комментарий про ручные
   приложения и `MODEL_SWITCH_REQUIRED` (как §13 codex), чтобы конфиг был source
   of truth и для ручного исполнения.
4. **`core/templates/review-report.md.j2`** — добавить во frontmatter поля
   `review_depth` и `full_review_offered` (под H2).

---

## Приоритет внедрения

1. **Детерминизм + зависимости (цели 0,1):** A (design contract), B (dependency
   impact), C (S-track plan), D (XS test-first), E (impl consumption).
2. **Review-гейты (цель 3):** H1–H4.
3. **Model guard (цель 2):** G — блокирующий в `design`/`discovery`, info-строка в
   `impl`/`xs-fasttrack`/`review` (схема «2+1»).
4. **Шаблоны и код (Факт A, этап 2):** F, I.

Такой порядок быстро поднимает качество roadmap/TDD/зависимостей и review-гейтов,
не трогая lifecycle во всех фазах сразу.

---

## Мои доп. предложения по эффективности

- **`Depends on` вместо просто «linear deps».** Явные id зависимостей в каждом
  шаге детерминируют порядок и дают impl-агенту проверяемый гейт «предшественники
  зелёные» (E1). Дешевле, чем повторно выводить порядок.
- **Risk-first для L уже встроен** в A1 (риск-шаги первыми) — это снижает
  вероятность, что Review/Manual найдут фундаментальную ошибку в конце.
- **Не делать full review всегда** — спрашивать только когда cascade/lite
  собирается выбрать дешёвый путь. Сохраняет скорость XS/S (совпадает с §15 codex).
- **Model guard как snippet** (G «эффективность») — но только если перейдёте на
  inline-рендер промптов; для paste-only оставить текст в файлах.
- **Шаблоны `.j2` — решить судьбу.** Раз они не рендерятся (Факт A), либо
  пометить их в `docs/process-artifacts.md` как «contract sample, authored by
  agent», либо реально подключить рендер. Сейчас это скрытый источник
  рассинхрона.
- **`review_depth` в ретроспективе** даст данные, где cheap-review пропускал
  проблемы — полезно для калибровки cascade.

---

## Решения (зафиксированы)

1. **Model guard — схема «2+1»** (Q1). Блокирующий guard только на `design.md` и
   `discovery.md` (Opus-tier); info-строка на `impl.md`/`xs-fasttrack.md`/`review.md`;
   `discovery-lite`/`review-lite`/`cheap`/`test-planner` не трогаем. См. раздел G.
2. **S-track `impl-plan.md` — только промпт** (Q2). Закрываем Факт C через раздел C
   (`test-planner.md`). Гейт в `artefacts.py` не делаем (I.2 вычеркнут).
3. **`.j2` шаблоны — контракт, без рендера** (Q3). Синхронизируем образцы (F1–F3) и
   честно переименовываем роль в docs (F4). Рендер не подключаем.
4. **Детект модели в Codex CLI — отсутствует** (Q4). Поэтому в ручном режиме guard
   работает как «подтвердите модель», а не авто-сравнение; это и продиктовало
   сужение до «2+1».
