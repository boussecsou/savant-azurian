# Application Insights: the 2 October 2026 fix

## Diagnosis

Hosted agent version 10 answered correctly (`/readiness` and `/responses` returned HTTP 200), but its OpenTelemetry and QuickPulse exports were refused with `Forbidden`. The `Monitoring Metrics Publisher` role was present for the project identity and absent for the hosted agent's identity. The `DisableLocalAuth` property was not set on Application Insights.

## Azure fix, made on request

- `Monitoring Metrics Publisher` was granted to the hosted agent's identity, on the Application Insights resource only.
- That resource was configured with `DisableLocalAuth=true`, following the Entra path recommended for Foundry traces.
- No code change, model change or redeployment was needed.

## Real verification

Two explicit invocations of version 10 answered `OK`. After the complete fix, Log Analytics holds, for the exact operation id of the second test, 1 `AppRequests`, 4 `AppDependencies` and 15 `AppTraces`. The recent logs of that session no longer contain `Forbidden` or `Exception occurred while publishing live metrics`. This validates ingestion and the absence of the observed errors for that session; the Live Metrics graphical panel was not inspected directly.

## Lesson for the template

The role is something the hosted agent needs after its first deployment, because its identity only exists then. `scripts/setup/grant-agent-roles.sh` grants it, together with the agent's other roles. If telemetry from the agent is missing, check this role first.

## Access, and a version trap

The usual Azure session is authenticated and usable outside a sandbox. In a sandbox the usual Azure configuration directory is read-only and `azd` cannot open its internal server: use the approved execution outside the sandbox, without copying credentials.

A local `azd` environment can still reference an older agent version. The tests of version 10 used `--version 10 --protocol responses`, and the log reads targeted the session id returned by that invocation explicitly. Do not interpret `azd ai agent show` without checking that context.

## Reference

[Entra authentication for Foundry traces](https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-ingestion-entra-authentication)
