# API PWA du BFF (Task 26.3)

Routes réservées au propriétaire, ajoutées au BFF existant (`src/savant/bff_api.py`).
Le code **ne déploie ni ne configure rien dans Azure** : sans les variables
ci-dessous, le BFF reste le callback OAuth seul, comme avant.

Contexte (décision du 30 octobre 2026) : Azure Static Web Apps est impossible sur
l'abonnement Azure for Students (politique de régions). La PWA (`pwa/`) tourne
**en local** ; le BFF et l'agent restent dans Azure. Le propriétaire s'authentifie
par **Microsoft Entra ID**, vérifié par l'authentification intégrée de Container
Apps (« Easy Auth ») devant le BFF. Étapes Azure : tâche 26.35.

```
PWA locale ─▶ proxy de dev local (ajoute le jeton Entra du propriétaire)
          ─▶ BFF (Container Apps + Easy Auth) ─▶ Managed Identity id-sa2-bff ─▶ Hosted Agent
```

## Routes

| Route | Rôle |
|---|---|
| `GET /api/oauth/notion/start` | Redirige (302) vers le consentement Notion pour le propriétaire. |
| `GET /api/oauth/notion/status` | `{"connected": true/false}` : le propriétaire a-t-il un grant utilisable ? |
| `POST /api/chat` | Relaie `{"message", "conversation_id"?}` vers `/responses` du Hosted Agent. |
| `POST /api/chat/stream` | Même relais, mais la réponse est transmise au fil de l'écriture (flux `text/event-stream`, voir ci-dessous). |
| `POST /api/warmup` | Réveille l'agent avec sa sonde sans outil ; `{"ready": true/false}`. |
| `GET /oauth/notion/callback`, `/readiness` | Inchangés, publics (appelés par Notion et par ACA). |

### Flux `/api/chat/stream`

Même corps et mêmes erreurs HTTP que `/api/chat` pour tout ce qui échoue **avant** le premier octet
(`401`, `403`, `422`, `502`, `504`). Ensuite le BFF ne transmet qu'un vocabulaire réduit, une ligne
`data: {json}` par événement :

| Événement | Contenu |
|---|---|
| `{"type":"delta","text"}` | Un morceau du texte de l'assistant. |
| `{"type":"tool","id","name","status":"running"}` | L'agent appelle un outil (nom seulement). |
| `{"type":"tool","id","status":"done"}` | L'outil a rendu son résultat. |
| `{"type":"done","conversation_id"}` | Fin normale ; l'identifiant à renvoyer au message suivant. |
| `{"type":"error","kind":"timeout"\|"upstream"}` | Échec après le début du flux. |

Le raisonnement, les arguments des outils et leurs résultats (les données Notion du propriétaire)
ne sont **jamais** relayés. Le délai de lecture de 120 s borne le silence entre deux événements,
et le flux entier est coupé à 220 s. Un flux qui s'arrête sans `done` ni `error` est signalé en
`error`. La PWA retombe sur `/api/chat` si cette route répond `404` (image BFF plus ancienne).

### Préchauffage `/api/warmup`

Envoie à l'agent la sonde de `savant.health` (texte dupliqué dans `bff_api.py`, un test garantit
qu'il reste identique) : un seul appel modèle, sans outil, sans Notion ni OAuth. Il réveille
l'hôte de l'agent et le client modèle avant le premier vrai message. La PWA l'appelle au chargement,
puis au retour sur l'onglet si le dernier réveil date de plus de 4 minutes. Il coûte un appel
modèle court, et rien ne garantit que la session réveillée soit celle qui servira la conversation :
le Journal de la PWA affiche la durée du préchauffage pour le mesurer.

Les routes `start` et `status` existent aussi sans préfixe (`/oauth/notion/start`)
pour les appels directs (tests `curl`, BFF lancé en local).

`conversation_id` est l'`id` de la dernière réponse de l'agent : le BFF le
renvoie à l'agent en `previous_response_id`. La PWA le garde et le renvoie au
message suivant ; le premier message n'en a pas. La réponse est
`{"conversation_id", "reply"}`. Erreurs : `401` pas d'identité, `403` pas
propriétaire, `422` entrée invalide, `502` agent en erreur, `504` agent trop lent
(délai de 120 s : l'agent peut mettre plus d'une minute pour une lecture Notion, 66 s mesurés
pour « liste mes tâches SA2 » ; il reste sous le délai de requête par défaut de l'ingress de
Container Apps, 240 s selon la documentation).

## Identité du propriétaire

Trois identifiants distincts, à ne pas confondre :

| Identifiant | Contenu | Rôle |
|---|---|---|
| `BFF_OWNER_OBJECT_ID` | *Object ID* Entra du compte du propriétaire (GUID) | Contrôle d'accès aux routes `/api` du BFF |
| `NOTION_OWNER_ID` | Clé fixe choisie côté serveur | Clé de stockage du token Notion, **même valeur** sur le BFF et l'agent |
| ID client de l'app registration | Identité de l'application BFF dans Entra | Audience du jeton vérifiée par Easy Auth |

- **Qui peut appeler** : Easy Auth valide le jeton Entra (signature, émetteur,
  audience) avant le BFF, puis ajoute les en-têtes `X-MS-CLIENT-PRINCIPAL-ID`
  (l'*Object ID* de l'appelant) et `X-MS-CLIENT-PRINCIPAL-IDP` (`aad`). Un client
  externe ne peut pas définir ces en-têtes (documentation Microsoft Learn,
  « Authentication and authorization in Azure Container Apps »). Le BFF les compare
  à `BFF_OWNER_OBJECT_ID` : en-tête absent → `401` ; autre appelant ou autre
  fournisseur → `403` (fail closed). Dans Entra, « User assignment required »
  n'assigne que le propriétaire : c'est la première barrière, le contrôle du BFF
  est la seconde.
- **Requêtes anonymes autorisées** : Easy Auth reste en mode « autoriser les
  requêtes anonymes » pour que `/readiness` et `/oauth/notion/callback` restent
  publics. Sans jeton, aucun en-tête d'identité n'existe et le BFF répond `401`
  lui-même.
- **Quel `user_id` pour Notion** : `NOTION_OWNER_ID`, une **clé fixe** (MVP
  mono-utilisateur). Ce n'est pas un identifiant Notion : le BFF et l'agent s'en
  servent comme clé de stockage du token. Le client ne peut ni la choisir ni la
  modifier. L'agent ne la compare plus à l'identité que Foundry injecte
  (`x-agent-user-id`) : l'endpoint est protégé par Entra, donc seuls les
  appelants autorisés l'atteignent. En cloud, l'identité d'appel de la
  plateforme (`x-agent-foundry-call-id`) reste exigée.
- **PWA locale** : le serveur de développement de `pwa/` obtient le jeton avec
  `az account get-access-token --resource <api://…>` et l'ajoute aux appels
  `/api` (voir `pwa/README.md`). Le navigateur ne voit jamais le jeton ; CORS est
  inutile derrière ce proxy.
- CORS n'est activé que si `PWA_ORIGIN` est défini (PWA appelant le BFF depuis une
  autre origine). CORS ne remplace pas le contrôle d'identité ci-dessus.

## Configuration (non secrète)

Variables d'environnement du Container App du BFF :

```dotenv
NOTION_OWNER_ID=<clé fixe, identique à celle de l'agent (azure.yaml)>
BFF_OWNER_OBJECT_ID=<Object ID Entra du propriétaire, ex. 0b1c2d3e-4f50-4a61-8b72-9c83d4e5f607>
AGENT_RESPONSES_URL=https://<compte>.services.ai.azure.com/api/projects/<projet>/agents/<agent>/endpoint/protocols/openai/responses?api-version=v1
PWA_ORIGIN=            # optionnel
```

- `BFF_OWNER_OBJECT_ID` : *Object ID* du compte utilisateur (Portail → Entra ID →
  Utilisateurs → Object ID, ou `az ad signed-in-user show --query id -o tsv`).
  GUID obligatoire dès que `AGENT_RESPONSES_URL` est défini ; ce n'est pas un secret.
- `AGENT_RESPONSES_URL` : endpoint `/responses` du Hosted Agent (HTTPS, hôte
  `*.azure.com`). Le BFF y poste les messages avec son Managed Identity
  (`NOTION_OAUTH_MANAGED_IDENTITY_CLIENT_ID`, scope `https://ai.azure.com/.default`).
  **Seule cette variable active les routes** ; elle exige alors `NOTION_OWNER_ID`
  et `BFF_OWNER_OBJECT_ID`. Un BFF qui a déjà `NOTION_OWNER_ID` sans cette URL
  reste un simple callback. L'endpoint de l'agent répond `400` (`Missing required
  query parameter: api-version`) sans ce paramètre : le BFF ajoute `api-version=v1`
  automatiquement quand l'URL n'en contient pas, et conserve celui que tu fournis.
  Un refus de l'agent est journalisé par son code HTTP seul (`chat_relay_failed
  status=400`), sans corps de réponse, URL ni jeton ; le client reçoit `502`.

## Avant de définir `AGENT_RESPONSES_URL` (sécurité)

Le BFF fait confiance à `X-MS-CLIENT-PRINCIPAL-ID`. Tant qu'Easy Auth n'est pas
actif sur le Container App, son ingress est public et **n'importe qui peut forger
cet en-tête** (l'*Object ID* n'est pas un secret). Ne définis donc
`AGENT_RESPONSES_URL` qu'**après** avoir activé Easy Auth et vérifié qu'un appel
sans jeton est refusé.

## État de la mise en service (vérifié le 2026-10-31)

**Vérifié**

- Routes publiques avec Easy Auth actif : `/readiness` répond `200` et
  `/oauth/notion/callback?state=x` répond `400`.
- Jeton obtenu avec `az account get-access-token --resource api://<client-id>`
  après la pré-autorisation d'Azure CLI sur le scope `user_impersonation`. Claims
  relevées : `aud` = ID client, `iss` = `login.microsoftonline.com/<tenant-id>/v2.0`,
  `ver` = `2.0`, `azp` = Azure CLI, `scp` = `user_impersonation`.
- Avec `AGENT_RESPONSES_URL`, `NOTION_OWNER_ID` et `BFF_OWNER_OBJECT_ID` définis,
  sur `/api/oauth/notion/status` : sans jeton `401`, faux jeton `401`, faux en-tête
  `X-MS-CLIENT-PRINCIPAL-ID` sans jeton `401`, jeton du propriétaire `200`.
- Hosted Agent version 24 déployée par le CD sur `d3d22a0`, avec la configuration
  Notion et `NOTION_OWNER_ID`.

**Non vérifié**

- Appel `POST /api/chat` et rôle Foundry Agent Consumer de `id-sa2-bff` sur l'agent
  `sa2-agent` (sans ce rôle, l'agent répond `401`).
- Consentement Notion via `/api/oauth/notion/start` depuis la PWA.
- Révocation puis reconnexion de l'accès Notion.
- WebSocket vocal avec Easy Auth (tâches 31 et 33).

## Mise en place côté Azure (résumé)

Étapes manuelles (tâche 26.35), faites dans le Portail ; rien n'est déployé par le dépôt.

1. **Fournisseur d'identité** : Container App → *Authentication* → *Add identity
   provider* → *Microsoft* → *Create new app registration* (tenant unique). Le
   Portail crée l'app registration, son service principal (Enterprise application),
   l'URI `api://<client-id>`, le scope `user_impersonation` et un secret client
   stocké comme secret du Container App. Ce secret vaut 365 jours : à renouveler.
2. **Réglages d'authentification** : *Restrict access* = **Allow unauthenticated
   access** (sinon `/readiness` et le callback Notion sont bloqués) ; *Client
   application requirement* = **specific client applications** avec l'ID d'Azure CLI
   `04b07795-8ddb-461a-bbee-02f9e1bf7b46` ; *Identity requirement* = **any identity**.
3. **Pré-autorisation d'Azure CLI** : app registration → *Expose an API* →
   *Authorized client applications* → ID d'Azure CLI, scope `user_impersonation`
   coché. Sans elle, `az account get-access-token` échoue avec `AADSTS65001` et
   `az login --scope …/.default` avec `AADSTS650057`.
4. **« Assignment required »** : non activé, car le tenant n'a qu'un utilisateur.
   Risque résiduel documenté : toute identité du tenant peut obtenir un jeton, mais
   Easy Auth n'accepte que les jetons demandés par Azure CLI et le BFF refuse (`403`)
   tout *Object ID* différent de `BFF_OWNER_OBJECT_ID`.
5. **Connexion d'Azure CLI** : les *Security Defaults* du tenant bloquent le flux
   device code (`AADSTS530035`). Utiliser `az login` par navigateur, sans
   `--use-device-code`.
6. **Rôle BFF → agent** : *Foundry Agent Consumer* attribué à `id-sa2-bff` sur la
   portée de l'agent `sa2-agent` (moindre privilège).
7. **Variables du Container App** : définir `NOTION_OWNER_ID`, `BFF_OWNER_OBJECT_ID`
   puis `AGENT_RESPONSES_URL` **en dernier**. Si `AGENT_RESPONSES_URL` est définie
   sans les deux autres, le BFF refuse de démarrer.

## Tests curl de contrôle

À lancer après `az login` (par navigateur). `<client-id>` est l'ID de l'app
registration ; ne publie ni jeton, ni *Object ID*, ni identifiant de tenant.

```bash
BFF=https://<fqdn-du-bff>
APP=api://<client-id>
TOKEN=$(az account get-access-token --resource $APP --query accessToken -o tsv)
code() { curl -s -o /dev/null -m 25 -w "%{http_code}\n" "$@"; }

code $BFF/readiness                                   # 200
code "$BFF/oauth/notion/callback?state=x"             # 400
code $BFF/api/oauth/notion/status                     # 401 : pas de jeton
code -H "Authorization: Bearer abc" $BFF/api/oauth/notion/status           # 401 : faux jeton
code -H "X-MS-CLIENT-PRINCIPAL-ID: <object-id>" -H "X-MS-CLIENT-PRINCIPAL-IDP: aad" \
     $BFF/api/oauth/notion/status                     # 401 : en-tête falsifié, sans jeton
code -H "Authorization: Bearer $TOKEN" $BFF/api/oauth/notion/status        # 200 : propriétaire
```

Avec « Allow unauthenticated access », Easy Auth ne rejette pas un faux jeton : il
le traite comme une requête anonyme, sans en-têtes d'identité (un faux jeton sur
`/readiness` donne donc `200`). C'est le **BFF** qui refuse les routes protégées
(`401` sans identité). Tant qu'`AGENT_RESPONSES_URL` n'est pas définie, toutes les
routes `/api/*` répondent `404` et ces tests ne prouvent rien sur l'identité.
