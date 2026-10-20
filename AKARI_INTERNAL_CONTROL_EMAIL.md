# Email to Internal Control: AKARI Diagnostic Tool

**To:** Sandra  
**Subject:** AKARI diagnostic tool: codebase review summary

Hi Sandra,

As requested, please see the presentation prepared by the Service team on the diagnostic tool. The team has submitted the code base, which is kept in Epson GitHub. I have analysed the code base and the summary is below.

It is a local diagnostic-assistance tool designed to help Epson service engineers translate complex projector troubleshooting information into clear, structured diagnostic guidance.

The tool accepts an engineer's symptom description and, where available, IPS Tool logs, photos, or Condition Diagnosis values. It then:

1. Parses IPS Tool data deterministically for error codes, sensor values, and operating history.
2. Retrieves relevant approved technical knowledge pages.
3. Uses a locally hosted AI model to produce a structured response with likely causes, ranked troubleshooting steps, confidence, source references, and an escalation draft where needed.

The purpose is decision support only: the engineer remains responsible for validating the diagnosis and performing the repair.

## Data and security approach

- AI inference runs locally on the physical computer; no external AI inference service is used.
- Access is protected at the application edge with two-factor authentication.
- The knowledge base is built from service material held by diagnostic engineers, such as service manuals, technical bulletins, and approved procedures.
- The intended scope excludes end-customer records. Source documents and knowledge content remain on the local environment.
- Diagnostic activity is logged for auditability and quality improvement, including the sources used and user feedback. The knowledge base is reviewed by a person before publication to the diagnostic system.

The Service team informed us that they have presented this to SEC and would like to take it forward for further development.

## Next steps

1. Mohammad Al Armouti and Sait Askar have been given access to Epson GitHub Enterprise so that they can use company resources and the code base stays with Epson. **Complete.**
2. Provide both with training on GitHub Enterprise and best practices for using AI in GitHub Enterprise. This is an approved EEB developer tool.

## Considerations if launched to service partners

The current status is proof of concept. If Epson decides to launch it for service partners, the following would need to be considered:

- **Compute capability:** The current tool depends on the processing speed of a single physical computer and is not scalable.
- **Epson-governed hosting:** Move the application, knowledge base, databases, backups, and model runtime to an approved Epson-managed environment with appropriate capacity, resilience, patching, and monitoring.
- **Identity and access management:** Replace the current edge-access approach with Epson corporate identity controls, role-based access, partner onboarding and offboarding, multi-factor authentication, and regular access reviews.
- **Data protection and retention:** Define the permitted data types, retention periods, deletion process, backup handling, audit-log access, and responsibilities with Internal Control, IT Security, Legal, and Data Protection.
- **Partner data separation:** Ensure that one service partner cannot access another partner's diagnostic history, uploaded logs, feedback, or any restricted technical content.
- **Knowledge-content governance:** Confirm which manuals, bulletins, parts information, and procedures may be made available to partners, and establish approval, versioning, expiry, and review ownership for all knowledge pages.
- **Security assurance:** Complete threat modelling, vulnerability assessment, penetration testing, secure configuration review, incident-response procedures, and ongoing patch and dependency management before external access is enabled.
- **Operational support:** Define service ownership, support model, availability expectations, monitoring, alerting, backup and recovery testing, and a process for handling model or diagnostic-quality issues.
- **AI governance and user guidance:** Provide clear partner-facing limitations, confidence indicators, source citations, escalation routes, and a requirement that recommendations are verified against current authorised service documentation.
- **Commercial and legal review:** Confirm licensing for the AI models and any third-party services, terms of use for partners, liability boundaries, and any contractual requirements for handling technical service information.
