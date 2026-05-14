# Codex comments on klc

Дата анализа: 2026-05-13.

## Кратко

`klc` выглядит как framework для управляемой работы LLM-агентов с большим
кодовым проектом. Он пытается решить три связанные задачи:

1. Не давать агенту каждый раз читать весь репозиторий, а строить
   индексы, module docs и ограниченные context bundles.
2. Вести каждую задачу как трассируемый ticket-flow: intake, discovery,
   test planning, design, build, review, integrate, learn.
3. Накапливать знания не в свободном чате, а в артефактах: `spec.md`,
   `impl-plan.md`, ADR, review reports, retrospectives, `.index.json`,
   `.klc/knowledge/*`.

Главная ценность проекта не в конкретных скриптах, а в попытке превратить
LLM из одноразового помощника в участника инженерного процесса с памятью,
границами полномочий и проверяемыми ссылками на факты.

## Концептуальные замечания

### 1. Разделить "агент" и "модель"

Сейчас документация в основном говорит "Claude" или "LLM agent". Лучше
ввести явную матрицу:

- роль агента: discovery, planner, test, implementation, reviewer,
  retrospective;
- требуемые способности: long context, tool use, code editing, reasoning,
  strict JSON output, cheap summarization;
- допустимые модели: high-end cloud model, cheaper cloud model, local model,
  external reviewer model;
- fallback: что делать, если модель недоступна или не поддерживает MCP.

Например, Discovery и Design требуют сильного reasoning и хорошей работы с
неопределенностью. Test planning и retrospective можно частично отдать более
дешевой модели. Review можно делать ансамблем: быстрый local/static слой,
затем профильные LLM reviewers, затем один сильный external reviewer только
для спорных или L-track изменений.

### 2. Сделать model profiles, а не только project profiles

Сейчас есть `profiles/generic` и `profiles/ue`, то есть профили кодовой базы.
Стоит добавить отдельный слой `model_profiles`, например:

- `fast-local`: без сетевых вызовов, ограниченный context, только индексы и
  статические проверки;
- `balanced-cloud`: стандартный режим для M-ticket;
- `deep-cloud`: L-ticket, ADR, cross-module design, security-sensitive work;
- `ci-headless`: без интерактивных вопросов, только проверки и отчеты;
- `external-audit`: независимая модель, которая не видела историю обсуждения.

Такой слой позволит явно контролировать стоимость, privacy и качество, а не
зашивать поведение в промпты.

### 3. Развести environments

Проекту нужны runtime profiles отдельно от project profiles:

- local developer machine;
- CI;
- air-gapped enterprise environment;
- Windows/Git Bash;
- Linux/macOS;
- shared klc checkout для многих проектов;
- repository-embedded klc.

Сейчас код частично Bash-first, частично Python-first, а `doctor` проверяет не
все предположения окружения. Лучше формализовать environment contract: какие
команды обязательны, какие optional, какие фазы могут работать offline, какие
требуют MCP или API keys.

### 4. Четче классифицировать знания

В проекте уже есть хорошая идея inline items: FACT, ASSUMPTION, DECISION,
QUESTION, CONFLICT. Ее стоит развить в явную модель типов знаний:

- derived knowledge: автоматически извлечено из кода и индексов;
- human-owned knowledge: решения, constraints, accepted trade-offs;
- agent hypothesis: временные гипотезы, которые не должны жить долго;
- process knowledge: уроки из retrospectives;
- policy knowledge: правила, которые уже стали обязательными checks;
- external knowledge: документация, Jira, wiki, provider docs.

Для каждого типа нужны разные правила freshness, authority и удаления.
Например, derived facts должны часто инвалидироваться при изменении файлов,
а human decisions не должны автоматически переписываться агентом.

### 5. Ввести жизненный цикл знания

Сейчас Learn предлагает обновлять knowledge base, но нет явной стадии
созревания знания. Хорошая схема:

1. Observation: заметка в review или retrospective.
2. Candidate: повторилось в нескольких ticket.
3. Rule proposal: предлагается как правило процесса или reviewer rule.
4. Accepted rule: человек принял.
5. Enforced check: правило стало скриптом, profile hook или reviewer prompt.
6. Retired: правило устарело и удалено с причиной.

Это защитит `.klc/knowledge` от превращения в кладбище старых советов.

### 6. Не все знания должны становиться markdown

Markdown удобен как human-facing источник, но для машинной проверки нужен
структурированный слой. Оптимальная архитектура:

- Markdown остается readable source of record.
- `.index.json` становится compiled graph.
- JSON schemas валидируют форму.
- query layer отвечает на вопросы "какие решения затрагивают модуль X",
  "какие assumptions устарели", "какие facts ссылаются на измененный файл".

То есть markdown не должен быть единственным API для knowledge base.

### 7. Добавить confidence и provenance

FACT с `src=file:line` уже хорош. Но для практики нужны дополнительные поля:

- `confidence=high|medium|low`;
- `source=code|human|docs|ticket|tool`;
- `verified_by=agent|human|script`;
- `verified_at=<date>`;
- `expires_at` или `ttl`;
- `invalidates_on=file-change|module-api-change|manual`.

Это особенно важно, если одна часть знаний получена из кода, другая из
документации, а третья из рассуждений агента.

### 8. Разделить память на working memory и institutional memory

Scratchpad и ticket artifacts хорошо работают как working memory. Но
institutional memory должна быть гораздо более строгой. Не каждый вывод из
scratch или retrospective должен попадать в `.klc/knowledge`.

Нужен promotion gate: агент может предложить knowledge update, но человек или
policy script должны решить, стоит ли это превращать в долгоживущее правило.

### 9. Сделать "knowledge decay" обязательной функцией

Большой риск такого framework - устаревшая уверенность. Если модуль изменился,
старые CLAUDE.md, facts, ADR links и cached Serena answers могут вводить агента
в заблуждение.

Нужны регулярные механизмы:

- per-module hash уже есть, его стоит расширить на knowledge invalidation;
- facts с `src=file:line` должны становиться stale при изменении файла;
- module CLAUDE.md должен иметь `generated_from_sha`;
- Discovery должен видеть предупреждение "context stale";
- retrospective should report stale-rate as a process metric.

### 10. Пересмотреть принцип "много документации на каждый ticket"

Подход RUP-like с большим количеством артефактов полезен для M/L задач, но для
XS/S может быть слишком тяжелым. Tracks уже есть, но важно, чтобы short tracks
были не просто "меньше шаблонов", а другой режим мышления.

Для XS лучше:

- one-page spec;
- direct test/build;
- lightweight review;
- no long-term knowledge unless обнаружен повторяющийся паттерн.

Иначе framework начнет мешать маленьким изменениям.

### 11. Формализовать "контекстный бюджет"

Идея "не читать весь проект" центральная, но ее стоит сделать измеримой:

- сколько tokens/символов может читать каждая фаза;
- какой процент public API допустим в context;
- когда можно открывать source files;
- когда Serena обязателен, а когда запрещен;
- когда agent должен остановиться и попросить narrow focus.

Это должно быть частью model profile и ticket track.

### 12. Сделать tool contracts первичнее prompts

Сейчас промпты описывают много правил, но часть правил должна жить не только в
тексте, а в исполняемых contracts:

- schema validation;
- phase transition validation;
- artifact presence validation;
- source freshness validation;
- diff scope validation;
- reviewer partial validation.

Промпт должен объяснять intent, а скрипт должен enforce critical invariants.

### 13. Улучшить независимость review

Multi-agent review полезен, но есть риск correlated failure: все reviewers
читают одинаковую spec, одинаковый context и могут повторить одну ошибочную
assumption.

Для важных изменений стоит добавить режим независимого review:

- один reviewer видит только diff + tests;
- другой видит spec + design + diff;
- external reviewer не видит внутреннюю recommendation;
- aggregator сравнивает расхождения.

Это повышает шанс поймать неверный framing.

### 14. Ввести "adversarial reviewer" для L-track

Отдельная роль: не искать обычные bugs, а атаковать выбранный дизайн:

- что если assumption неверна;
- какой module boundary нарушен;
- где hidden coupling;
- что станет невозможно поддерживать через 6 месяцев;
- какие rollback paths не доказаны.

Для L-track это может быть ценнее, чем еще один обычный reviewer.

### 15. Разделить design options и implementation plan по authority

Options - пространство выбора. Impl plan - уже выбранная линия исполнения.
Если они живут слишком близко, агент может преждевременно рационализировать
один вариант.

Лучше явно хранить:

- rejected options with reasons;
- selected option with human ack;
- implementation plan derived from selected option;
- design debt accepted by human.

Это уже частично есть, но стоит сделать это машинно проверяемым.

### 16. Добавить "decision ledger"

ADR полезен для крупных решений, но многие маленькие решения не заслуживают
ADR. Нужен lightweight decision ledger по ticket или module:

- decision id;
- date;
- owner;
- context;
- alternatives rejected;
- expiry or revisit condition;
- affected modules.

Такой ledger может быть compiled из `[!DECISION]` items.

### 17. Поддержать разные уровни privacy

Если framework предполагает cloud models и external reviewers, нужен явный
privacy mode:

- какие файлы можно отправлять внешней модели;
- какие patterns считаются secret;
- можно ли отправлять diffs;
- можно ли отправлять proprietary module docs;
- какие фазы обязаны работать local-only.

Это особенно важно для enterprise и game/UE проектов.

### 18. Добавить redaction layer

Перед передачей context внешним моделям нужен redaction/filter stage:

- secrets;
- internal URLs;
- customer data;
- private Jira text;
- license-sensitive code;
- binary asset paths, если они раскрывают unreleased content.

Лучше делать это отдельным skill, а не надеяться на reviewer prompt.

### 19. Сместить часть проверки из LLM в static tooling

Для многих reviewer concerns LLM не лучший первый слой. Хороший pipeline:

1. Static checks and profile hooks.
2. Structural search rules.
3. Dependency/API diff checks.
4. LLM reviewers only interpret non-trivial findings and design risk.

Это снизит стоимость и уменьшит hallucinated review findings.

### 20. Сделать "agent portability" явной целью

Чтобы framework не был привязан к одному клиенту, у каждого agent prompt
должен быть machine-readable manifest:

- inputs;
- outputs;
- required tools;
- forbidden tools;
- expected files written;
- completion signal;
- schema;
- max context;
- model capability requirement.

Тогда один и тот же framework сможет работать с Claude Code, Codex, CI runner,
local model runner или ручным оператором.

### 21. Ввести compatibility tests для prompts

Промпты тоже являются кодом. Для них нужны тесты:

- prompt references existing files;
- output examples match validators;
- completion signals match phase scripts;
- no stale paths like `framework/...`;
- no instruction to mutate phase directly if lifecycle owns phase.

Это можно проверять простым static prompt linter.

### 22. Сфокусировать framework на "trust boundaries"

Сильная сторона проекта - human gates. Ее стоит формализовать как trust
boundary model:

- агент может предлагать;
- скрипт может проверять;
- человек подтверждает intent, direction, merge approval;
- CI подтверждает execution safety;
- knowledge promotion требует authority.

Такой подход лучше масштабируется, чем список фаз сам по себе.

### 23. Сделать процесс менее линейным для research-heavy задач

Текущий flow хорош для delivery tickets. Но некоторые задачи сначала требуют
spike/research. Для них нужен отдельный track или branch:

- Research ticket;
- hypothesis list;
- experiments;
- findings;
- decision to convert into delivery ticket or close.

Иначе research будет искусственно притворяться Design или Discovery.

### 24. Добавить "unknown budget"

У ticket сейчас есть uncertainty score, но стоит добавить operational rule:
если unknowns слишком велики, нельзя идти в Build. Нужно либо answer questions,
либо create spike, либо split ticket.

Это снизит риск, что агент начнет кодить поверх неясной постановки.

### 25. Сильнее использовать module ownership

Если проект большой, affected_modules - мало. Полезно знать:

- owner/team;
- maturity;
- test reliability;
- API stability;
- criticality;
- allowed reviewers;
- deployment risk.

Эти параметры могут жить в module CLAUDE.md или отдельном module manifest.

### 26. Добавить "knowledge conflicts" как first-class сущность

CONFLICT items уже есть, но их можно развить:

- conflict between ADR and current code;
- conflict between spec and module ownership;
- conflict between generated CLAUDE.md and source;
- conflict between two decisions;
- conflict between docs and tests.

Такие conflicts должны блокировать не только phase, но и knowledge promotion.

### 27. Улучшить эволюцию профилей

Профили `generic` и `ue` - хороший старт. Следующий шаг:

- profile inheritance;
- project-local extensions;
- versioned profile schema;
- profile compatibility check;
- profile-specific knowledge namespaces.

Иначе с ростом числа окружений профили станут трудно поддерживать.

### 28. Сделать CI usage не вторичным, а равноправным

Сейчас многие шаги предполагают ручной запуск агента. Для зрелого процесса
нужно четко разделить:

- interactive mode: агент пишет артефакты;
- headless mode: CI проверяет, что артефакты соответствуют контрактам;
- assisted mode: CI создает job cards для агента.

CI не должен зависеть от интерактивного LLM, чтобы сказать "контракты
сломаны".

### 29. Добавить cost accounting как архитектурное ограничение

Метрики уже упоминают tokens/cost, но стоит сделать cost budget частью
планирования:

- max cost per phase by track;
- max external review cost;
- max Serena live calls;
- cache hit target;
- prompt compression target.

Это особенно важно, если framework используется на большом потоке tickets.

### 30. Сделать "done" не только archived

Архивация ticket - хорошо, но Done должен включать:

- code merged;
- artifacts consistent;
- knowledge candidates handled;
- stale assumptions marked;
- metrics rolled up;
- follow-up tickets created or explicitly rejected.

Иначе Learn может превратиться в формальность.

## Более технические замечания, которые мешают концепции

1. Review pipeline сейчас потенциально считает "partials pending" успешным
   review, потому что `review.sh` выходит `0`, а `review.py` трактует `0` как
   approval.
2. В документации и скриптах остались ссылки на старый `framework/...` layout.
3. Упоминаются отсутствующие prompts `core/agents/impl.md` и
   `core/agents/plan.md`.
4. `doctor` падает без `jinja2` и `PyYAML`, но в проекте нет явного dependency
   manifest.
5. `lifecycle.advance(current_phase)` выглядит как no-op, но пишет новую
   запись в `phase_history`.
6. `learn --continue` переводит ticket в `archived` до проверки, что archive
   destination свободен.
7. `metrics rollup` не учитывает archived tickets.
8. `items.py` не проверяет duplicate item ids.
9. `consistency_check.py` слабее своего описания в docstring.
10. Agent prompts иногда предлагают напрямую менять `meta.json:phase`, что
    конфликтует с идеей единого lifecycle controller.

## Главный вывод

Самая перспективная линия развития `klc` - не добавлять больше фаз, а усилить
границы и контракты:

- model profiles вместо неявной зависимости от одного LLM;
- environment profiles вместо неявного Bash/Linux допущения;
- knowledge lifecycle вместо простого накопления markdown;
- executable validators вместо правил только в prompts;
- authority model для каждого знания и артефакта;
- cost/privacy/freshness как такие же важные constraints, как tests.

Тогда проект может стать не просто набором скриптов для Claude, а переносимой
операционной системой для agent-assisted engineering.
