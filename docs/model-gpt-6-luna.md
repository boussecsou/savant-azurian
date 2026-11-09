# Modèle Savant : GPT-6 Luna

La migration du 8 octobre 2026 réutilise le déploiement Azure OpenAI existant
`sa2-gpt-6-luna` dans `azai-savant-azurian-2` : modèle `gpt-6-luna`, version
`2026-09-22`, Global Standard, capacité 150. Elle ne provisionne aucune ressource.

## Configuration et authentification

La variable GitHub `FOUNDRY_MODEL_NAME` vaut `sa2-gpt-6-luna`. La CD la transmet
à `AZURE_AI_MODEL_DEPLOYMENT_NAME` dans l'environnement azd, puis `azure.yaml`
l'injecte dans la nouvelle version du Hosted Agent. Modifier la variable seule
ne change pas les versions déjà publiées. Le pipeline garde OIDC et son contrôle
de CI réussie sur le SHA exact de `main`.

Pour une exécution locale, utiliser les mêmes valeurs :

```env
AZURE_OPENAI_BASE_URL=https://azai-savant-azurian-2.openai.azure.com/openai/v1/
AZURE_AI_MODEL_DEPLOYMENT_NAME=sa2-gpt-6-luna
```

L'URL complète `/openai/responses?api-version=2025-04-01-preview` affichée au
portail n'est pas une URL de base pour `ChatOpenAI`. Le client utilise le chemin
v1 `/responses`, sans paramètre `api-version`.

Le bearer token conserve le scope `https://ai.azure.com/.default` et
`DefaultAzureCredential` : compte développeur local, Managed Identity du Hosted
Agent dans Azure. L'identité existante de `sa2-agent` possède déjà le rôle
`Cognitive Services OpenAI User` sur `azai-savant-azurian-2` ; ce scope couvre
aussi le nouveau déploiement dans la même ressource. Aucun rôle supplémentaire
ni secret n'est nécessaire.

## Responses et historique

`build_model()` utilise explicitement `use_responses_api=True` et
`output_version="responses/v1"`. GPT-6 Luna limite le function calling via
Chat Completions au raisonnement `none` ; Responses permet de conserver le
raisonnement par défaut et les tools LangGraph.

L'historique reste géré par LangGraph. Les requêtes modèle ont `store=False`
et demandent `reasoning.encrypted_content` pour rejouer les éléments de
raisonnement après un tool ou une restauration de checkpoint. Le client
n'utilise pas `previous_response_id` côté modèle. Le `previous_response_id`
du protocole public du Hosted Agent reste géré par le serveur Responses.

Les tests passent par les vrais clients OpenAI/LangChain avec un transport HTTP
simulé, en synchrone et asynchrone : réponse, tool `echo`, reprise du modèle et
relecture d'un historique sérialisé. La validation réelle utilise le modèle
existant puis le smoke test de la CD ; elle ne prouve pas l'accès réel à Notion.

En cas de retour à l'ancien modèle, rétablir `FOUNDRY_MODEL_NAME=gpt-5.6-luna`
puis publier explicitement une nouvelle version avec le pipeline existant.
Le workflow ne fait pas de rollback automatique.

Références : [authentification Entra Azure OpenAI](https://learn.microsoft.com/en-us/azure/foundry-classic/openai/how-to/managed-identity),
[GPT-6 Luna et function calling](https://developers.openai.com/api/docs/models/gpt-6-luna).
