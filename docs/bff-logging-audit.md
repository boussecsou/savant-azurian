# Backend log audit, 20 October 2026

Scope: the backend Container App and its environment, the Python and Docker code, the recent Container Apps logs, two accessible Log Analytics workspaces and four local diagnostic files. No real secret was retrieved for comparison. No historical data was deleted and no RBAC assignment was added.

## Azure findings

- Active revision: the `v1` image, Docker entry point `python -m savant.oauth_callback`, with no command override.
- Inspection inside the container: `UVICORN_ACCESS_LOG_DISABLED=True`.
- No diagnostic setting on the app or the environment; the environment's log destination and Log Analytics configuration were null.
- Dapr disabled, no OpenTelemetry export configured in the environment, no Application Insights or OTEL variable in the container. The backend entry point initializes no telemetry SDK. The OTEL dependencies installed in the image are not, by themselves, an activation of instrumentation.
- HTTPS enforced; secret variables were inspected by name only.
- Platform metrics stay available: `Requests`, unit `Count`, one series returned over the last 24 h. No metric setting was changed.

Ingress HTTP logs can contain the path **with the query string**: do not enable `ContainerAppHTTPLogs` for this OAuth environment without a validated way to remove it before storage. The current configuration does not export them. Reference: [Container Apps log schema](https://learn.microsoft.com/en-us/azure/container-apps/log-monitoring).

## Risks and code fixes

HTTP access logging was already disabled. The HTML responses and OAuth errors were also generic. The process, however, imposed no global protection against dependency messages, Python warnings or Uvicorn exceptions. Unexpected callback errors were swallowed without a usable event.

`src/savant/bff_logging.py` now imposes fixed-event output: no formatting of arguments, third-party messages, extras, paths, exceptions or stack traces. The access logger is filtered even if it is accidentally enabled. Python warnings go through this configuration. Existing third-party loggers are disabled and new propagated logs go through the filter. Propagated warnings and errors stay represented by generic events.

`oauth_callback.py` configures this protection before building the service, passes the same configuration to Uvicorn and emits fixed events for success, refusal, outage and startup failure. Azure metrics do not depend on this Python configuration. This hardening concerns the backend only.

## Historical search

- Recent logs: 6 console lines and 24 system lines returned, with no OAuth code or query pattern, cookie, Authorization, token, named secret or JWT detected. The query asks for the last 300 lines; it is not an exhaustive export.
- The two workspaces (configured retention: 30 days) return no line referring to the app or its environment over the last 30 days. The search uses the backend and environment names and aggregates the results on the service side.
- Four local files: 1,985 lines. The 30 occurrences of the word Authorization are 20 already masked headers, 6 RBAC references and 4 SDK names in User-Agent. No confirmed unmasked secret candidate in this search.
- The results kept in the audit's scratch folder are filtered configurations and counters; the raw historical messages were not copied there.

## Validation

Command:

```bash
python -m pytest -q tests/test_bff_logging.py tests/test_oauth_runtime.py tests/test_notion_oauth.py
```

**44 tests passed.** Real Uvicorn tests on localhost with fictitious values only: success, OAuth refusal, callback outage, uncaught exception, dependency logs, Python warning and startup failure. The fake codes, states, tokens, cookies, Authorization values and exception contents are absent from the output; the success and error events stay present.

A public test on `/readiness` with a fictitious query string, Authorization and cookie: HTTP **200**, `{"status":"ready"}`, no synthetic marker in the returned console logs. This check is not a real OAuth test, nor proof about all of Microsoft's internal journals.

## Application status and limits

**The Python hardening was fixed and tested locally, but not yet deployed at the time of the audit.** Inspection of the container confirmed `HARDENED_LOGGING_MODULE_PRESENT=False`. No dangerous active Azure configuration was found to change. Deploying a new image needs an explicit request under the learning framework of [AGENTS.md](../AGENTS.md).

After merge and a green CI on `main`, use **Publish BFF** manually to build and publish the fixed image to the registry. Then update the Container App explicitly with the verified digest; check the new revision, `/readiness` and the synthetic logs. See [the full procedure](bff-release-procedure.md). No current workflow updates Container Apps automatically.

The historical search depends on the data that is accessible and retained; it does not prove the absolute absence of a past leak. Future direct prints to stdout, custom handlers or independent instrumentations and exporters must be reviewed separately. The generic error events deliberately limit detailed diagnosis. No new durable log storage was enabled.
