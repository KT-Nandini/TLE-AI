Texas Legal AI SaaS (Strict RAG Architecture)
Version

1.0

Status

MVP scope, production oriented

1. Product Overview

This project is a public SaaS legal information platform that provides Texas specific legal explanations via a conversational interface.

The system:

Uses a fixed expert persona (Texas Legal Expert, “Thomas”)

Explains law in plain English

Is jurisdiction locked to Texas

Does not provide legal advice

Does not create an attorney client relationship

All answers must be grounded in a curated Texas Legal Library maintained by administrators.

2. Users and Roles
Admin

Upload and manage legal documents

Control the legal knowledge base

View all conversations

Masquerade as users

Monitor usage

Regular User

Create an account

Start multiple conversations

Resume past conversations

Ask Texas legal questions

3. Authentication

Email and password

Google OAuth

Individual accounts only

No organizations in MVP

4. AI and Prompting
System Prompt

A strict system prompt named Texas Legal Expert (TLE AI) already exists

It defines:

Legal guardrails

Mode gating

Citation discipline

Output structure

This prompt is immutable

Developer Prompt

Injects retrieved context

Reinforces “no fallback” behavior

Does not modify legal logic

5. Core Architectural Principle

The model is never trusted to decide facts.
All truth comes from retrieved documents.

If retrieval fails, the system must refuse.

6. Document Ingestion Pipeline
Supported Formats

PDF

DOCX

TXT

Text Extraction

Preserve:

Page numbers

Section numbers

Headings

Do not normalize away legal structure

Chunking Rules

Chunk size: 600 to 900 tokens

Overlap: 100 to 150 tokens

Never split across:

Statute sections

Rule numbers

Case headings

Required Metadata Per Chunk

Every chunk must include:

{
  "title": "Texas Family Code",
  "source_file": "texas_family_code_2024.pdf",
  "page": "42",
  "section": "§153.002",
  "authority_level": "statute",
  "domain": "family",
  "jurisdiction": "TX"
}


Do not infer or guess missing values.

7. Authority Levels

Allowed values:

statute

rule

case

practice_guide

Priority order:

statute

rule

case

practice_guide

8. Retrieval Logic (Strict RAG)
Query Flow

User submits a question

Backend classifies domain (family, criminal, civil)

Backend rewrites query using statutory language

Vector search with filters:

jurisdiction = TX

domain = inferred domain

Retrieve top 20 chunks

Re-rank by:

authority level

presence of section numbers

Select final 6 to 8 chunks

Empty Retrieval Handling

If no chunk survives filtering, send to the model:

Retrieved Context:
[NO APPLICABLE KNOWLEDGE SET MATERIAL LOCATED]


Never inject fallback text.

9. Model Invocation Rules
Allowed Inputs

System prompt (TLE AI)

Developer instructions

Retrieved Context only

Forbidden

Web browsing

Public law databases

Search tools

General legal knowledge

10. Citation Rules

All legal claims must map to retrieved chunks

Citations must reference uploaded files

Missing authority must be labeled:

CITATION NEEDS VERIFICATION


Never fabricate citations

11. Conversation System

Multiple conversations per user

Memory is per conversation only

Older messages summarized when context grows

Memory summaries never override retrieved law

12. Admin Panel Requirements
Document Management

Upload files

View metadata

Re embed documents

Delete documents

Oversight

View conversations

Masquerade as users

Monitor usage

13. User Interface

ChatGPT style interface

Conversation list

Resume past chats

Streaming responses

14. Out of Scope (MVP)

Stripe billing

Multiple jurisdictions

User document uploads

Plan based limits

Web browsing

15. Development Order

Document ingestion and chunking

Vector store with metadata

Strict retrieval and filtering

Model invocation with enforced RAG

Conversation persistence

Admin panel

Frontend

16. Acceptance Criteria

The system is correct if:

It never cites public law or web sources

All citations map to uploaded documents

Missing sources trigger refusal

The assistant never guesses

Legal tone follows the TLE AI prompt

17. One Line Summary

A Texas legal AI where the model reasons, the documents decide truth, and nothing is allowed to guess.