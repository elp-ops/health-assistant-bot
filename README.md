# Health Assistant Bot

A Telegram-based AI health assistant for caregiving: appointments, reminders, a running health record, doctor contacts, and photo/report parsing, built on Claude with Google Workspace integration.

This code is based on a live, functional, private bot in daily use managing a real person's healthcare since April 2026, not a demo or proof of concept.

## What it does

- Logs appointments straight to Google Calendar from natural conversation
- Sends Telegram reminders ahead of appointments and procedures
- Keeps a running health record in a Google Doc
- Stores doctor contacts in a Google Sheet
- Reads photos of medical reports and files them automatically
- Has a configurable personality, calm and direct by default

## Stack

Python, Telegram Bot API, Anthropic Claude (conversation via tool use, vision for document parsing), Google Calendar/Docs/Sheets/Gmail APIs.

## Status

Genericised public template in progress. The real implementation exists and runs daily, this public version is being stripped of personal data and hardcoded names so anyone can deploy their own. Code and setup guide coming.
