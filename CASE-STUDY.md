# Case study: building an instrumented service you can rebuild from nothing

Ayobami Ajetunmobi, September 2026.
Repo: the runbook is in README.md. Everything below is measured, not estimated.

## The short version

I containerised an AI support agent, ran it on Kubernetes, instrumented it, put Prometheus and
Grafana over it, and then deleted the whole machine and rebuilt it from my own written
instructions. That last step is the part that matters. It found five defects in a procedure I
had written the day before, with full context, about a system I had just built myself.

## What the system is

A Flask service calling Amazon Bedrock, built as a multi stage image running as a non root user,
deployed to a local two node Kubernetes cluster. Prometheus discovers it through pod annotations
and scrapes it. Grafana displays four panels provisioned from a JSON file in the repo.
Alertmanager holds four alert rules defined in the Prometheus values file.

Two application metrics:

- agent_requests_total, a counter labelled endpoint, method, status
- agent_request_duration_seconds, a histogram labelled endpoint only, eight buckets

The endpoint label comes from the Flask route TEMPLATE rather than the request path, and falls
back to "unmatched". That is a deliberate cardinality control: without it, anything probing
random URLs mints a new time series per URL.

## Honest boundaries

Stated because a portfolio piece that oversells is worse than one that underdelivers.

- Not highly available. One replica of everything.
- Not persistent. Prometheus retention is 2h with no volume, Grafana persistence is off.
  Deliberate on a laptop, wrong anywhere else.
- Metrics only. No logs, no tracing.
- The /work endpoint is SYNTHETIC. It sleeps on an exponential distribution and fails 10 percent
  of the time on purpose. It exists because /chat needs Bedrock credentials that are not present
  locally. Its latency numbers describe the generator, not a real workload.
- Single process. Under gunicorn each worker would keep its own registry.
- The Grafana password in this repo is "admin". Acceptable for a cluster reachable only by
  port-forward from the machine running it, and unacceptable anywhere else.

## Measured results

All figures from live runs, not estimates.

| Measure | Value |
|---|---|
| Clean machine to working stack | about 15 minutes |
| Prometheus install | about 2 minutes, zero pod restarts |
| Same stack via kube-prometheus-stack, for contrast | 17 minutes, 8 restarts |
| Memory, full stack on a 4.803 GiB Docker VM | 1.78 GiB |
| Series exposed by the application endpoint | 41 |
| Prometheus head series, whole stack | about 43,000 |
| p95 on /work across three independent runs | 470ms, 479ms, about 500ms |
| Mean on /work | 130ms to 170ms, against a designed 150ms |

The 41 figure is worth a note. An earlier run measured 25 series from the same unchanged code.
The difference was traffic, not code: series appear as label combinations are exercised.
**Series count is a property of the traffic, not of the source.** That is precisely why an
unbounded label is dangerous, because you cannot bound it by reading the code.

The head series figure reproduced within rounding across runs weeks apart, on rebuilt clusters.
That is the closest thing to a controlled repeat available here, and it is why I trust the rest.

## Managed versus self hosted

I ran the same workload under Datadog to have an informed opinion rather than a preference.

| | Prometheus stack | Datadog |
|---|---|---|
| Install to ready | about 2 min | 5 min 47 s, zero restarts |
| Memory on this host | 1.78 GiB | 1.83 GiB |
| Dashboards out of the box | none, I provision mine | 6 default monitors, unconfigured |
| Cost of a cardinality mistake | memory I already paid for | billed custom metrics |

The memory figures are close enough to be interesting and NOT a clean comparison: the two runs
used different load generator configurations. What is fair to say is that on a small cluster the
managed agent is not the lightweight option people assume, and the burden is roughly a wash.

The cost model is the real difference. My application produced 4 metric names, which Datadog
bills as 28 custom metrics. The Datadog tooling watching my application produced 33 integration
metrics, and its Operator alone emitted 365 samples per collection against my application's 27.
Of 37 metrics collected, 0 were used in any dashboard and 2 had been queried in 30 days.

Separately, I had already measured what one unbounded label does: 218 new series per minute at
3.6 requests per second, which is 313,000 a day on a toy application, or 86 million a day at
1,000 requests per second. On self hosted Prometheus that is a memory problem you can fix on a
Tuesday. On a per metric managed platform it is an invoice that arrives thirty days later.

**Managed services do not remove the consequences of a design mistake. They change the currency
you pay in.**

## What the rerun found

I wiped Docker completely and ran only what the README said. Five defects:

1. **No directory step.** A relative path resolved against the parent directory and found a
   DIFFERENT kind-config.yaml, building a three node cluster instead of two. No error. It built
   the wrong thing successfully.
2. **helm --set-file treats the backslash as an escape character**, so a Windows path silently
   lost its separator. The -f flag in the SAME command line worked, because -f does not go
   through that parser.
3. **A verification step sent the reader to a second terminal and never sent them back.**
4. **Opening the README itself** from the wrong directory opened an empty file.
5. **helm reported STATUS: deployed for Grafana whose datasource pointed at a Prometheus service
   that did not exist**, because an earlier step had silently failed. The pod was 1/1 Running
   with zero restarts. Every panel would have read "No data", and the obvious suspects would
   have been the dashboard JSON, the queries, and the datasource, in that order, for about
   twenty minutes.

Three of the five shared one root cause, so the fix was structural rather than cosmetic: every
command block that touches a file now opens with its own directory change. Repetitive to read,
impossible to paste wrong. **A runbook has to be correct when someone copies one block out of
the middle, because that is what people actually do.**

## The pattern underneath

Four separate occasions where a system reported health it did not have:

- A load balancer failing open when every target behind it was unhealthy.
- An alert staying silent when the service it watched disappeared entirely.
- A DaemonSet reporting desired 1, current 1, ready 1, all in agreement, while watching one of
  two nodes. The second node was tainted and the DaemonSet had no toleration, so the controller
  computed one eligible node and was satisfied.
- helm reporting deployed for a system that could not work.

None of these are bugs. **The system is not lying. It is answering a narrower question than the
one you think you asked.** The skill is knowing which question a given green tick actually
answers.

There is a related habit worth naming. Three times in three days, in three different systems, an
empty result looked like missing data and was a wrong query: a service filed under a legacy name,
a metric renamed at an ingestion boundary, and a time window that predated the data.
**An empty result is a claim about your query, not about the world.**

## What I would do next

Stated as scope, not as gaps I failed to notice.

- Logs and traces. This is metrics only and says so.
- A monitor that alerts on the ABSENCE of data. Deleting the agent pod produced no detectable
  outage, because the replacement started faster than the staleness window. A push based system
  has no failed scrape event to catch, so absence has to be watched for explicitly.
- Alertmanager grouping, silencing, inhibition and a real receiver. Detection and handoff are
  proven; delivery is not.
- Running this against a managed control plane so the Bedrock path produces real latency instead
  of a synthetic endpoint.
- Replacing the grafana/grafana chart, which now prints a deprecation warning on install.
