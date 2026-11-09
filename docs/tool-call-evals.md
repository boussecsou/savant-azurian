# Évaluation des appels d'outils (pass^k)
Un agent peut réussir un appel d'outil une fois puis échouer en répétition. Cette évaluation mesure
`pass^k` : la probabilité que k essais indépendants réussissent **tous**, par cas et en moyenne.

## Commandes

```bash
# Validation hors ligne : aucun client, aucun credential, aucun coût.
python -m scripts.evaluate_tool_calls
# Appels réels au modèle (PAYANTS, authentification Entra existante), 3 essais par cas.
python -m scripts.evaluate_tool_calls --run --trials 3
# Sous-ensemble pour itérer moins cher.
python -m scripts.evaluate_tool_calls --run --trials 2 --limit 4
```

`--trials` est borné à 1-8 et `--limit` à 1-12. Chaque cas affiche
`{"id","trials","passes","pass_at_1","pass_hat_k"}`, puis un résumé global ; le code de sortie
vaut 1 dès qu'un cas n'a pas réussi tous ses essais. Sans `--run`, le script valide le JSONL
(clés, ids uniques, outils connus, `expected_tool` offert ou null, arguments contradictoires).

## Limites

- Coût : chaque essai est une inférence payante (12 cas × 3 essais = 36 appels).
- Schémas d'outils minimaux et fictifs, avec une coroutine jamais exécutée : on mesure la sélection et les arguments, pas le comportement réel de Notion, du MCP ou du web.
- Évaluation en un seul tour : tous les appels doivent viser l'outil attendu ; une clarification est jugée par l'absence d'appel, pas par la qualité du texte.
