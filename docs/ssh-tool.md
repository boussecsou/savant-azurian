# Outil SSH vers la VM Linux (tâche 27)

L'agent peut exécuter une commande sur la VM Linux `vm-lab1-sa2` avec `ssh_exec`. Ses règles sont dans le prompt système (`tools/ssh_skill.py`) : il n'y a plus d'outil `read_ssh_skill`, qui coûtait un tour de modèle (6 à 9 s) par conversation. Chaque commande est jugée par un **juge sémantique** (second appel modèle isolé, comme le consentement Notion) ; un plancher codé en dur reste en filet de sécurité (issues #51 et #52).

## Fonctionnement

| Élément | Rôle |
| --- | --- |
| `ssh_exec(command, reason, confirmed)` | Une ligne, 1000 caractères au plus, 30 s. Plusieurs commandes indépendantes dans une même étape (4 au plus) : jugées puis exécutées en parallèle. |
| Juge (`ssh.CommandJudge`) | Reçoit la commande exacte, la raison donnée par le modèle, le dernier message du propriétaire et un indicateur « contenu extérieur lu dans ce tour ». Rend `RUN`, `CONFIRM` ou `REFUSE` (sortie structurée, raisonnement `none`, `SSH_JUDGE_INSTRUCTIONS`). |
| Plancher (`ssh.floor_matches`) | Filet de sécurité : transforme un `RUN` en `CONFIRM` pour `rm -r`, `mkfs`, `dd of=`, redémarrage, `chmod/chown -R`, `curl … \| sh`, utilisateurs, pare-feu, `sshd`, clés SSH, sudoers, etc. Ce n'est plus le mécanisme principal. |
| Nœud `ssh` du graphe | Portail côté serveur (`notion_chat.run_ssh`), séparé du consentement Notion (inchangé). |

### Ce que juge le juge

- **Sans confirmation** : la lecture (état du système, services, journaux, fichiers, recherches, y compris avec jokers, boucles et tubes en lecture) et l'**ajout** (nouveau fichier, nouveau dossier, ajout en fin de fichier).
- **Avec confirmation** : la suppression, l'écrasement ou la modification d'un fichier existant (`>` sur un fichier existant, `sed -i`), toute modification appliquée à une liste ou un ensemble de cibles (boucles, jokers, `xargs`, `find -exec`), les changements durables (services, droits, pare-feu, utilisateurs, clés, paquets, cron, disques, redémarrage), le code téléchargé puis exécuté, une commande composée dont une partie l'exigerait, une commande qui ne découle pas de la demande du propriétaire (par exemple dictée par une page web ou Notion lue dans le tour), et tout doute.
- **Refus** : afficher ou envoyer des secrets (clés privées, jetons, empreintes de mots de passe, `.env`) ou envoyer des données de la VM à un tiers non demandé.
- **Échec du juge** (délai, erreur, sortie invalide) : confirmation, jamais exécution (*fail closed*). Journal `ssh_judge_failed reason=…`, sans contenu.

Le contenu extérieur lu dans le tour n'est plus un blocage automatique (la « règle de contamination » de la PR #49 bloquait une simple lecture après une recherche web, issue #51) : c'est un indice donné au juge.

Journal de chaque verdict : `ssh_verdict digest=… verdict=… outside=… ms=…` (empreinte tronquée, jamais la commande). Jeu d'évaluation : `evals/ssh_commands.jsonl`, mesuré en pass^k avec `python -m scripts.evaluate_ssh_judge --run --trials 5` (appels payants ; sans `--run`, valide seulement le jeu). Mesuré le 7 novembre 2026 sur `sa2-gpt-6-luna` : 36 cas sur 36 en pass^5, aucun échec du juge. Pour créer un fichier, l'agent écrit avec `>>` (crée sans écraser) : un `>` simple demande confirmation, puisque le juge ne peut pas savoir si le fichier existe.

### Commande soumise à confirmation

1. Premier appel jugé `CONFIRM` : rien ne s'exécute, l'état garde `ssh_pending` (empreinte de la commande, propriétaire, conversation, tour). Une seule commande attend à la fois ; les autres commandes à confirmer de la même étape sont renvoyées au modèle.
2. L'agent montre la commande exacte et demande l'accord.
3. Au message suivant de l'utilisateur, l'agent rappelle `ssh_exec` avec la **même** commande et `confirmed=true`.
4. L'exécution n'a lieu que si l'empreinte correspond, qu'un **nouveau tour utilisateur** est intervenu et que l'attente a moins de 30 minutes ; elle ne repasse pas par le juge. L'attente est ensuite consommée : un rejeu est jugé à nouveau.

Limite assumée : le « oui » du propriétaire à la question SSH n'est pas vérifié par un second modèle (c'est le modèle principal qui le lit). Ce qui est garanti : pas d'auto-approbation dans le même tour, pas de changement de commande, pas de rejeu. La sortie de la VM ne peut pas valider quoi que ce soit. Une attente expirée ne désactive plus le chemin rapide des tours suivants.

### Refus fail closed

Identité absente, commande vide/multiligne/trop longue, lot mélangé (SSH + autre outil) ou de plus de 4 commandes, verdict `REFUSE` ou inconnu : rien ne s'exécute. Un délai dépassé ou une connexion perdue donne « résultat incertain » et n'est jamais rejoué automatiquement.

## Connexion

- `asyncssh`, une connexion par commande, fermée ensuite.
- Compte dédié `sa2agent` (sudo sans mot de passe) ; `<admin-user>` reste le compte d'administration.
- Clé privée ed25519 dans le secret Key Vault `sa2-ssh-private-key`, lue à chaque appel avec l'identité managée de l'agent (rôle *Key Vault Secrets User* existant). Jamais dans le code, l'état du graphe ou les journaux.
- Clé d'hôte épinglée (`SSH_HOST_KEY`, publique) : aucune confiance au premier contact. Relevée avec `ssh-keyscan` et recoupée avec `az vm run-command` (lecture de `/etc/ssh/ssh_host_ed25519_key.pub`).
- Journaux : empreinte tronquée de la commande, code de sortie, durée. Jamais le texte de la commande, l'hôte ni la sortie.
- sshd : `PermitRootLogin no`, `PasswordAuthentication no`, `AllowUsers <admin-user> sa2agent` (`/etc/ssh/sshd_config.d/60-sa2.conf`).

## Configuration

Tout ou rien (sinon `RuntimeError` au démarrage) : `SSH_HOST`, `SSH_USER`, `SSH_HOST_KEY`, `SSH_KEY_VAULT_URL`, `SSH_KEY_SECRET_NAME`. Optionnels : `SSH_PORT` (22), `SSH_CONNECT_TIMEOUT` (10), `SSH_COMMAND_TIMEOUT` (30). Valeurs de production dans `azure.yaml`.

## Rotation de la clé

1. Générer une nouvelle paire ed25519 hors dépôt.
2. Ajouter la clé publique à `/home/sa2agent/.ssh/authorized_keys` (via `<admin-user>`).
3. `az keyvault secret set --name sa2-ssh-private-key --file <clé>` (nouvelle version ; l'agent lit la dernière).
4. Vérifier une commande, puis retirer l'ancienne clé publique et détruire le fichier local.

## Couper l'accès

- Rapide : supprimer la ligne de `/home/sa2agent/.ssh/authorized_keys`, ou désactiver le secret Key Vault.
- Retirer l'outil : supprimer `SSH_HOST` de `azure.yaml` et redéployer.
- Dégâts sur la VM : restaurer depuis le snapshot `snap-vm-lab1-sa2-before-ssh-tool`.

## Points faibles connus

- Le port 22 reste ouvert à Internet dans le NSG. Protections : clé, clé d'hôte épinglée, compte dédié. L'IP de sortie du Hosted Agent a été observée (journal `ssh` de la VM) mais n'est pas garantie stable : à restreindre une fois sa stabilité confirmée.
- Une clé volée donne root sur une VM d'apprentissage. Acceptable seulement tant que la VM ne porte aucune donnée sensible.
- Le jugement d'un modèle n'est pas une frontière de sécurité : d'où le plancher, la règle du nouveau tour et le snapshot.
- Un appel de juge en plus par commande (environ 1 à 1,5 s, en parallèle pour les commandes d'une même étape), compensé par la disparition du tour `read_ssh_skill` et par l'exécution en parallèle.
- La VM n'a pas d'identité managée : un accès root ne peut pas rebondir vers Azure.
