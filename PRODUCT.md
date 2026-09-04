# Python Blaster TTS

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Delegated explicitly by the user. Python application with FastAPI, SQLite,
an embedded PJSUA2 SIP/RTP library, and offline Piper speech synthesis.
The browser is a local operations and analytics workspace served by the same
Python process. Charts are bundled locally; Excel reports are generated in Python.

## Product Purpose

Place concurrent personalized outbound calls through a SIP trunk, play speech
after answer, accept repeat/agent choices, and bridge the customer to an agent.
Persist call evidence for analysis: separate legs, AMD, transfers, durations and
termination initiators, with filtered dashboards and Excel/CDR exports.

## Users

Assumption selected under delegated scope: a Spanish-speaking campaign operator
working at a computer, managing a contact list and monitoring calls.

## Capabilities and Constraints

No Asterisk, hosted TTS, external database, queue server, or other intermediary
service. Application logic is Python; SIP and TTS use embedded native libraries.
Concurrency is configurable. Agent bridging consumes two SIP channels.
All application configuration, including SIP passwords, belongs in TOML, as
explicitly requested by the user. SIP credentials are read directly from that file. User authentication stores
salted password hashes in SQLite; no readable user password is retained.
The existing installation has a configured SIP trunk and a local Piper voice.
Simulation remains available for isolated tests. Credentials never enter reports.

## Operating Context

One running application process, localhost access, multiple local user accounts
with administrator, operator and analyst permissions.
Scope: create/import a campaign, preview personalized text and local speech, start/pause/stop,
monitor states, inspect results, simulate keypad interactions and analyze historical
calls. The workspace has Dashboard, Campaigns, Calls/CDR, Reports and Operations sections.
Operations adds trunks, templates, schedules, automatic reports, alerts, settings,
users and audit. One trunk remains a supported first-class configuration.
Historical records without telemetry retain their original data and explicit gaps.
Calls with probable human detection or keypad interaction are recorded locally
as compact Ogg Opus. Recording starts after that evidence; voicemail/unknown
without interaction is not recorded. Audio access is restricted by role.

## Evidence on Hand

Existing running implementation, user-provided SIP diagnostics, configured voice,
local simulation and SIP integration tests. UI inspection data is synthetic and
isolated from the actual database. A SIP leg identifies a remote endpoint, not the
physical person who answered or hung up. Unknown evidence stays unknown.
