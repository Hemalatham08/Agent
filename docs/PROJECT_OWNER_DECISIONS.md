\# iFive AI ERP Agent — Project Owner Decisions



\*\*Project:\*\* iFive AI ERP Agent  

\*\*Business:\*\* ABC Fasteners \& Industrial Supplies  

\*\*Status:\*\* Approved direction  

\*\*Purpose:\*\* Authoritative requirements for future development



\## 1. Product Vision



iFive AI ERP Agent is an intelligent, reusable ERP agent platform that understands natural-language business questions, determines the appropriate ERP operations, retrieves actual ERP data through controlled tools, performs analysis when required, and presents accurate answers.



It must not become a chatbot limited to predefined question patterns or hardcoded responses.



\## 2. Read-Only ERP Capability Expansion



The Agent must expand through dedicated, secure, read-only ERP tools in the following order:



1\. Products

2\. Inventory

3\. Sales Orders

4\. Purchase Orders

5\. Dispatch

6\. Quality

7\. Accounting / Invoices

8\. Payments / Outstanding Balances



Each tool must have strict input validation, controlled data access, bounded results, safe error handling, and appropriate output schemas.



\## 3. Grounding and Answer Reliability



\- Agent answers must be grounded exclusively in retrieved ERP tool results.

\- The Agent must never invent ERP records, identifiers, quantities, counts, statuses, dates, or financial values.

\- Unsupported questions must receive a clear capability explanation.

\- Tool execution failures must not be represented as successful retrieval.

\- Missing, ambiguous, or incomplete data must be communicated accurately.

\- Derived calculations must use retrieved data and correct calculation logic.

\- The Agent must not treat its conversational history or its own previous answers as authoritative ERP data.

\- Successful tool execution and answer correctness must be tested.



\## 4. Multi-Turn Conversations



Multi-turn conversation is required.



Initially:

\- The frontend supplies validated and bounded conversation history.

\- The backend validates history independently.

\- Conversation history is context, not ERP evidence.

\- The Agent must retrieve current ERP data whenever a question requires business facts.

\- History must not override current ERP results.

\- Context length and message count must be bounded.



Persistent conversation storage may be introduced later.



\## 5. Authorization and Deployment



Current deployment:

\- Local demonstration.

\- Unrestricted authorized local-user access.

\- No production-grade multi-user authorization is assumed.



Future architecture:

\- Backend-enforced role-based access control.

\- Authorization must never be decided by the LLM.

\- Roles and permissions must be enforced independently of prompts.

\- Architecture must progressively support multiple users, organizations, and ERP implementations.

\- Tenant and organization isolation must be designed before production multi-organization deployment.



\## 6. Future Write Operations



Write operations may begin only after read-only Agent reliability is established.



Approved implementation order:



1\. Create Product

2\. Update Product

3\. Create Purchase Order

4\. Create Sales Order

5\. Inventory Adjustment

6\. Dispatch Creation

7\. Invoice Creation



No write capability is authorized merely because it is listed in this roadmap.



\## 7. Mandatory Write Safety Requirements



Every write operation must implement:



1\. Input validation.

2\. Business-rule validation.

3\. Permission and authorization checks.

4\. A preview of the proposed operation.

5\. Explicit user confirmation.

6\. Independent backend authorization.

7\. Idempotency protection.

8\. Audit persistence.

9\. Database transaction safety.

10\. Database verification after execution.

11\. Safe rollback or clearly handled failure behavior.

12\. Accurate user-facing success or failure reporting.



The LLM must never independently bypass these controls.



\## 8. Shared ERP Read-Service Architecture



The secure ERP read-service layer is the future shared foundation for:



\- AI Agent tools.

\- Conventional ERP APIs.

\- Future ERP integrations.



Migration requirements:

\- Incremental migration only.

\- Preserve existing API behavior.

\- Regression-test every migrated endpoint.

\- Retain legacy implementations until replacements are proven.

\- Avoid unnecessary rewrites.

\- Do not remove working legacy code prematurely.



\## 9. Engineering Rules



\- Inspect before modifying.

\- Understand existing architecture before proposing implementation.

\- Prefer small, focused changes.

\- Avoid unrelated refactoring.

\- Do not introduce arbitrary SQL generation by the LLM.

\- Maintain strict tool schemas and controlled ERP access.

\- Add automated tests for every meaningful capability.

\- Verify database results independently when testing business answers.

\- Clearly distinguish implemented functionality from planned functionality.

\- Document important architectural changes.

\- Do not commit generated files, secrets, databases, or temporary artifacts unintentionally.



\## 10. Change Approval



These decisions represent the approved project direction.



If an implementation requires a change to:

\- Product scope.

\- Security architecture.

\- ERP data access boundaries.

\- Write-operation safety.

\- Migration strategy.

\- Approved implementation order.



The coding AI must explain the proposed change and obtain project-owner approval before proceeding.



\## 11. Immediate Development Priority



The immediate priority is to audit the current project and establish reliable, fully grounded read-only Agent behavior.



No write operations or broad architecture migrations should begin before their prerequisites are established and approved.

