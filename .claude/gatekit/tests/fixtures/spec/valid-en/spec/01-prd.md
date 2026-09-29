# Notes app — product requirements

## Problem

People have nowhere to put short notes, so they message themselves in chat.

## Current state (measured)

| Metric | Current value | Source | Measured on |
|---|---|---|---|
| Time to save a note | not measured | not measured | 2026-09-10 |

> ⚠️ Assumption 1: save time has never been measured.

## Goals

- Saving a note completes in under 3 seconds.

## Non-goals

- Sharing is out of scope for this round.

## Users

| User | Situation | What they do today | What they need |
|---|---|---|---|
| Individual | On the move | Messages themselves | A fast save |

## Features

### F1 — Write a note

The user types text and saves it.

## Acceptance criteria

- **F1** — Given text is entered, when saved, then it appears in the list.

## Assumption ledger

| # | Assumption | Basis | Impact if wrong | How to confirm |
|---|---|---|---|---|
| 1 | Save time has never been measured | No logs exist | The goal loses its basis | Add instrumentation |
