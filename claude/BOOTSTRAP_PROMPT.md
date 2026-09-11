# Bootstrap prompt pro Claude Code — spustit přímo v repu Barakuda

Tenhle text zkopíruj a vlož jako PRVNÍ zprávu Claude Code ve VS Code, v repu
barakuda (poté, co jsi tam nakopíroval CLAUDE.md a .claude/agents/).

---

Prošel jsem tenhle repo jen zvenku (bez přístupu ke kódu). Ty na něj vidíš
přímo — udělej následující:

1. Prozkoumej strukturu repa: adresáře, vstupní body, hlavní moduly,
   závislosti (requirements.txt / pyproject.toml / setup.py).
2. V CLAUDE.md doplň sekce "Co to je" a "Stack" reálnými fakty — 2–4 věty,
   jen co skutečně vidíš v kódu, žádné dohady.
3. Rozhodni, jestli tenhle projekt potřebuje doménově specifického
   kontrolního subagenta (obdoba physics-check z Thermelytry) — např.
   kontrolu jednotek, numerické stability, konzistence dat, bezpečnosti
   protokolu apod.
   - Pokud ano: pořádně dopiš .claude/agents/domain-check.md.
   - Pokud ne: ten soubor smaž.
4. Pokud v repu ještě neexistují ARCHITECTURE.md a BUILD_ORDER.md, navrhni
   jejich kostru (jen strukturu, ne vyplnit vše) a zeptej se mě, než je
   vyplníš celé.
5. Zkontroluj, jestli modelové přiřazení u subagentů dává smysl
   (test-runner a project-explorer na haiku, code-reviewer a domain-check na
   sonnet) — uprav, pokud je repo tak velký/kritický, že to neplatí.
6. Na závěr mi stručně shrň: co jsi našel, co jsi upravil, a co je potřeba,
   abych rozhodl já.

Nedělej zatím žádnou revizi kódu samotného — to je až další krok, až bude
tohle nastavení hotové.
