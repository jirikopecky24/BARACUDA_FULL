# Jak tohle použít

1. Zkopíruj `CLAUDE.md` do kořene repa `barakuda` (pokud tam nějaký už je,
   sluč ručně — needit dvakrát).
2. Zkopíruj `.claude/agents/*.md` do `.claude/agents/` v repu.
3. V Claude Code (ve VS Code, v tomto repu) spusť obsah `BOOTSTRAP_PROMPT.md`
   jako první zprávu — Claude Code si to sám dotáhne na míru podle
   skutečného kódu (to já odsud vidět nemůžu).
4. Až bootstrap doběhne a `domain-check` je hotový nebo smazaný, řekni
   Claude Code, ať udělá revizi celého programu — to je tvoje fáze 2.
5. Fáze 3 — UI/UX: až bude revize hotová, přidej skill `ui-ux-pro-max`
   (github.com/nextlevelbuilder/ui-ux-pro-max-skill) do `.claude/skills/` —
   buď stažením repa ručně, nebo ať to udělá Claude Code přímo v repu (na
   tvém stroji na GitHub vidí).

## Další věci, co stojí za přidání (fáze 4)
- Vybrané skills z github.com/travisvn/awesome-claude-skills nebo subagenty
  z github.com/VoltAgent/awesome-claude-code-subagents — vybrat jen to, co
  sedí na Python stack, needit tam vše najednou.
- Hook na automatický `ruff`/`black` po uložení souboru, pokud ho ještě
  nemáš — ušetří kolo promptu za formátování.
- Sleduj náklady, jak přibývá subagentů — subagent v izolovaném kontextu umí
  spotřebovat řádově víc tokenů než hlavní vlákno. Spouštět jen tam, kde to
  fakt pomůže, ne na všechno automaticky.

## Poznámka k přístupu
Tohle je claude.ai chat, ne Claude Code — nemám přímý přístup k tvému
lokálnímu repu ani k soukromým GitHub repům, a nemůžu použít ani GitHub
token, i kdybys mi ho dal (to je mimo to, co v tomhle rozhraní smím dělat).
Proto poslední krok — doladění na skutečný kód — musí udělat Claude Code
přímo ve VS Code, kde na repo skutečně vidí.
