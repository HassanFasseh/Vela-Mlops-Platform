# Vela - Frontend Redesign & UX Implementation

You already know this codebase, its backend, API endpoints, authentication, roles, models, deployments, monitoring, drift detection, remediation, tickets, teams, API keys, and existing functionality.

Your task is to **redesign and implement the frontend of Vela as a polished, production-quality MLOps platform**.

Do NOT rebuild the backend.
Do NOT invent backend functionality.
Do NOT change working APIs unless absolutely necessary.
Preserve all existing functionality and integrations.

The goal is to make Vela feel like a serious, modern infrastructure/ML platform - not a generic AI SaaS dashboard.

---

# 1. Product identity

Product name:

**Vela**

Positioning:

> Self-hosted MLOps for organizations that cannot send their data to the cloud.

Vela is designed for:

* Hospitals
* Banks
* Universities
* Government agencies
* Other organizations with strict data/privacy requirements

Core promise:

> Deploy. Monitor. Understand. Act.

The product should communicate:

* Privacy
* Control
* Reliability
* Observability
* Technical sophistication
* Simplicity despite infrastructure complexity

The user should feel that Vela is a serious piece of infrastructure.

Avoid the visual language of generic AI startups.

Do NOT use excessive:

* Purple gradients
* Neon colors
* Giant rounded cards
* Excessive glassmorphism
* Random floating blobs
* Stock AI imagery
* Marketing-heavy layouts
* Excessive animations

Prefer a visual identity inspired by:

**Linear + modern developer tools + Grafana + MLflow + premium enterprise software**

but do not copy any of them.

---

# 2. Overall frontend architecture

The application should have three major experiences:

1. Public landing page
2. Admin application
3. Team-member application

Use the same underlying design system and component library across the authenticated application.

Do not create two completely separate applications.

Use role-based navigation and capabilities.

Conceptually:

```text
                    VELA
                      │
              ┌───────┴───────┐
              │               │
           ADMIN          TEAM MEMBER
              │               │
       Full control      Assigned resources
```

---

# 3. Landing page

The landing page must be extremely minimal.

IMPORTANT:

The landing page should be **non-scrollable**.

It should fit entirely within the viewport:

```text
100vw × 100vh
```

No vertical page scrolling.

The landing page should feel more like an elegant entrance/portal to an infrastructure product than a conventional marketing website.

## Structure

Center the main content approximately around the middle of the viewport.

Include:

### Vela

A short tagline:

> Self-hosted MLOps.
> Your models. Your infrastructure. Your data.

Then one primary CTA:

**Get Started**

Potential secondary link:

**Documentation**

At the very bottom, use a minimal footer containing only a few links such as:

* Documentation
* GitHub
* About
* Privacy

Do not add large marketing sections.

Do not add pricing.

Do not add testimonials.

Do not add feature grids.

Do not add a huge navbar.

Do not add a long explanation of the product.

The landing page should be extremely clean.

---

# 4. Landing page visual design

Use a predominantly:

**white / off-white / black**

visual language.

You may introduce **one restrained accent color** for interactive elements and selected graphics.

The background should contain subtle technical/ML graphics.

Possible concepts:

* Abstract neural network
* Data points
* Feature vectors
* Model inference paths
* Statistical distributions
* Monitoring signals
* Connected nodes
* Deployment topology
* Subtle grid
* Data streams

The graphics should be:

* subtle
* elegant
* slow-moving if animated
* low contrast
* technically meaningful
* non-distracting

Do NOT make the background look like a generic AI particle animation.

The background should feel like a visualization of a real ML system.

Use animation sparingly.

The landing page should still look excellent with animations disabled.

---

# 5. Authentication

Preserve the existing authentication implementation.

Do not redesign authentication logic unless necessary.

Create a polished authentication experience that matches Vela's visual identity.

Support the existing:

* Username/password authentication
* Admin-created users
* First-login password change
* Role-based access

Clearly communicate when a user must change their password.

---

# 6. Authenticated application shell

Create a premium application shell.

Desktop-first, but fully responsive.

Use:

* Persistent sidebar
* Top bar
* Workspace/user information
* Breadcrumbs where useful
* Search/command functionality where appropriate
* Notifications
* User menu
* Clean content area

The sidebar should be compact and professional.

Avoid oversized navigation.

Use clear icons with labels.

---

# 7. ADMIN EXPERIENCE

The admin dashboard is the central control plane for Vela.

The admin should be able to understand the health of the entire platform at a glance.

## Admin navigation

Structure the navigation logically around:

### Overview

### Models

* Model Registry
* Deployments
* Versions

### Monitoring

* Model Health
* Drift
* Infrastructure

### Teams & Access

* Teams
* Users
* API Keys

### Automation

* Remediation
* Webhooks
* Retraining

### Tickets

### Documentation

### Settings

Only expose routes/features that actually exist in the current backend.

If an equivalent feature already exists under a different route/name, preserve its functionality.

---

# 8. ADMIN OVERVIEW

The admin overview should feel like a real operational command center.

At the top:

```text
Good morning, [user]

Platform Status
● Operational
```

Then high-level metrics such as:

* Total models
* Active deployments
* Healthy deployments
* Drift alerts
* Open tickets
* Active users

Do not turn every metric into a giant card.

Use a restrained visual hierarchy.

Then show:

## Model health

A professional table with information such as:

* Model
* Version
* Team
* Deployment status
* Drift
* Latency
* Last activity

Use clear status indicators.

Example:

```text
News Classifier     v1.8.2     Production    ● Healthy     2.1% drift    82ms
Fraud Detection     v2.1.0     Production    ⚠ Warning     7.8% drift    91ms
Sentiment Model     v1.4.1     Staging       ● Healthy     1.2% drift    64ms
```

Use real data from the existing API.

Do not fabricate data.

---

# 9. TEAM MEMBER EXPERIENCE

Team members should see a much simpler version of Vela.

They should NOT be exposed to infrastructure details they do not have permission to manage.

Their mental model should be:

> My models
> → Are they healthy?
> → Is anything wrong?
> → What should I do?

Navigation should focus on:

* Overview
* My Models
* Deployments
* Monitoring
* Drift
* Tickets
* API Keys
* Documentation
* Settings

Only show resources assigned to that user/team.

Respect all existing permission logic.

Never expose models, API keys, tickets, or team resources outside the user's authorization scope.

---

# 10. TEAM MEMBER DASHBOARD

The member dashboard should prioritize actionable information.

Show:

* Assigned models
* Deployment status
* Model health
* Drift status
* Recent alerts
* Open tickets
* Recent activity

Example model presentation:

```text
Sentiment Classifier

Production
v1.4.1

● Healthy

Drift       2.1%
Latency     82ms
Confidence  96.4%

View Model →
```

If a model requires attention, make it immediately obvious.

Example:

```text
⚠ Significant drift detected

Sentiment Classifier

The input distribution has changed significantly.

View analysis →
```

---

# 11. MODEL DETAIL PAGE

This should be one of the strongest pages in the entire application.

Create a rich but clean model detail experience.

Header:

```text
← Models

Sentiment Classifier
v1.4.1

● Production / Healthy
```

Include tabs or equivalent navigation:

* Overview
* Performance
* Drift
* Deployment
* API
* Documentation

Only implement tabs corresponding to real functionality.

---

# 12. MODEL HEALTH

Show important operational metrics:

* Predictions per minute
* p95 latency
* Confidence
* Drift score
* CPU
* Memory

Use charts where they communicate trends.

Do not create charts just for decoration.

Charts should support investigation.

For example:

```text
Predictions / minute
        ╭──────╮
   ╭────╯      ╰────╮
───╯                 ╰──
```

And:

```text
p95 latency
────────────────────────
```

And:

```text
Drift score - last 2 hours
```

Use appropriate visualization libraries already present in the project, or introduce a well-maintained charting library if required.

---

# 13. DRIFT EXPERIENCE

This is one of Vela's key differentiators.

Make drift analysis a first-class experience.

Do not simply display:

```text
Drift Score: 0.82
```

Instead explain what happened.

Show:

### Drift Overview

* Overall drift score
* Detection status
* Threshold
* Statistical test
* Time detected

Then:

### Population / feature breakdown

Show:

| Signal      | Change | p-value | Status |
| ----------- | -----: | ------: | ------ |
| text_length |   +31% |   0.001 | High   |
| language    |   +18% |   0.012 | Medium |
| confidence  |   -12% |   0.021 | Medium |

Use the actual backend data.

---

# 14. AI DRIFT EXPLANATION

Make the AI explanation visually distinct but not gimmicky.

Example:

### AI Analysis

> The model is receiving longer inputs and a higher proportion of non-English text compared with its training distribution. This may explain the recent reduction in prediction confidence.

Then show:

### What changed

* Input length increased
* Language distribution shifted
* Confidence decreased

Then:

### Recommended action

Depending on the actual backend capabilities:

* Review data
* Investigate drift
* Retrain
* Open ticket

Do not invent actions that don't exist.

The AI should feel like an **operational analyst**, not a chatbot.

---

# 15. AUTOMATED REMEDIATION

Make remediation understandable.

Users should be able to see:

```text
Drift threshold
      ↓
Condition triggered
      ↓
Automated action
      ↓
Result
```

For example:

```text
Drift > 0.70

        ↓

GitHub Issue created

        ↓

Retraining workflow triggered
```

Show:

* Trigger condition
* Threshold
* Action
* Last execution
* Status
* Result

If the backend supports configuring remediation per model, provide a clear configuration UI.

---

# 16. DEPLOYMENT EXPERIENCE

Deployment should feel like a guided workflow.

Support the existing functionality for:

* HuggingFace model deployment
* Custom model upload
* Docker build
* GitHub Actions
* Kubernetes deployment

Do not expose Kubernetes complexity unnecessarily.

Instead show a clear lifecycle:

```text
Model submitted
      ✓
Validation
      ✓
Build
      ✓
Container created
      ✓
Deployment
      ●
Health check
      ○
Monitoring
```

Use real deployment status from the backend.

---

# 17. MODEL UPLOAD

Make uploading a model simple.

The user should understand:

* What they are uploading
* Where it is stored
* Which workspace/team owns it
* What metadata is required
* What happens next

Include the existing model-card information:

* Dataset
* License
* Performance notes
* Known limitations

Do not overwhelm the user with infrastructure details.

---

# 18. TEAMS & ACCESS

Admin interface for:

### Users

* Create user
* Username
* Password
* Role
* Team membership
* Status

### Teams

* Create team
* Add/remove users
* Assign models

### API Keys

Clearly show:

* Key name
* Scope
* Team
* Model permissions
* Creation date
* Revocation

Never expose secrets after creation if the backend doesn't allow it.

---

# 19. TICKET SYSTEM

Create a professional issue/ticket interface.

Team members:

* Create ticket
* Select model
* Select type
* Select severity
* Describe problem
* Track status

Admins:

* See all tickets
* Filter
* Change status
* Add resolution notes
* Link tickets to models

Use clear states:

```text
Open
Investigating
Resolved
Closed
```

Make severity visually obvious but restrained.

---

# 20. MODEL DOCUMENTATION

Model documentation should feel like a proper model card.

Organize:

* Overview
* Dataset
* License
* Performance
* Limitations
* Deployment information
* Version

Make it readable by both technical and non-technical team members.

---

# 21. DESIGN SYSTEM

Before implementing the redesign, inspect the existing frontend and establish a coherent design system.

Define reusable:

* Colors
* Typography
* Spacing
* Border radius
* Shadows
* Buttons
* Inputs
* Tables
* Cards
* Badges
* Alerts
* Charts
* Modals
* Dropdowns
* Tabs
* Empty states
* Loading states
* Error states

Avoid one-off styling.

Use reusable components.

Do not create slightly different versions of the same component throughout the application.

---

# 22. STATES

Every important page must account for:

### Loading

Use appropriate skeletons rather than blank screens.

### Empty

Explain what the user can do next.

### Error

Explain the problem and provide a recovery path.

### Success

Give clear feedback.

### Permission denied

Explain that the user does not have access without leaking protected information.

### No data

Do not show broken charts or empty tables.

---

# 23. RESPONSIVE DESIGN

The application must work properly on:

* Desktop
* Laptop
* Tablet
* Mobile where practical

The admin control plane can be desktop-first.

Do not simply shrink the desktop layout on mobile.

Tables should have deliberate responsive behavior.

Charts should remain readable.

Sidebars should collapse appropriately.

---

# 24. ACCESSIBILITY

Target WCAG 2.2 AA where practical.

Ensure:

* Keyboard navigation
* Visible focus states
* Semantic HTML
* Sufficient contrast
* Accessible form labels
* Accessible status indicators
* Do not rely solely on color
* Screen-reader-friendly interactive elements

---

# 25. PERFORMANCE

Keep the application fast.

Pay particular attention to:

* Large monitoring datasets
* Charts
* Tables
* Polling/live updates
* API requests
* Code splitting
* Lazy loading
* Memoization where appropriate

Do not repeatedly fetch data unnecessarily.

Use the existing data-fetching architecture if it is sound.

---

# 26. IMPORTANT IMPLEMENTATION RULES

Before changing code:

1. Inspect the existing frontend.
2. Identify all routes.
3. Identify all API integrations.
4. Identify authentication and role logic.
5. Identify existing reusable components.
6. Identify existing styling/design system.
7. Identify which features are already implemented.
8. Identify missing frontend pieces.
9. Create the proposed information architecture.
10. Create the component hierarchy.

Then implement.

Do not blindly rewrite the application.

Preserve working functionality.

Do not invent API endpoints.

Do not invent backend data.

Do not replace existing authentication.

Do not remove existing functionality simply because it isn't part of the visual redesign.

If something is unclear, inspect the existing implementation before making assumptions.

---

# 27. IMPLEMENTATION ORDER

Do not attempt to redesign every page simultaneously.

Implement in this order:

### Phase 1 - Foundation

* Design tokens
* Typography
* Colors
* Application shell
* Sidebar
* Top bar
* Buttons
* Forms
* Tables
* Status components
* Loading/error/empty states

### Phase 2 - Landing + authentication

* Landing page
* Authentication
* First-login password flow

### Phase 3 - Admin

* Admin overview
* Models
* Deployments
* Teams
* Users
* API keys

### Phase 4 - Team member

* Member overview
* My Models
* Deployments
* API keys
* Tickets

### Phase 5 - Monitoring

* Model health
* Metrics
* Charts
* Infrastructure monitoring

### Phase 6 - Drift

* Drift overview
* Feature breakdown
* Statistical information
* AI explanation
* Recommended actions

### Phase 7 - Automation

* Remediation configuration
* Webhooks
* GitHub issues
* Retraining workflows

### Phase 8 - Documentation + polish

* Model cards
* Documentation
* Settings
* Accessibility
* Responsive behavior
* Performance
* Error states

---

# 28. QUALITY BAR

The finished frontend should feel like a product that could be shown to:

* ML engineers
* Data scientists
* DevOps engineers
* CTOs
* Security teams
* Enterprise customers

It should look and feel **production-ready**.

The most important principle:

> **Vela should make complicated MLOps operations feel simple without hiding important information.**

The interface should answer these questions immediately:

### Admin

> Is the platform healthy?

> Which models are running?

> Which models need attention?

> Which teams have access?

> What deployments are happening?

> Is infrastructure healthy?

### Team member

> Are my models healthy?

> Is something drifting?

> Why is it drifting?

> What should I do?

> How do I use my model?

---

# 29. Final instruction

Start by analyzing the existing frontend and backend integration.

**Do not start coding immediately.**

First return:

1. Current frontend architecture
2. Current routes
3. Current API integrations
4. Current role/permission implementation
5. Existing reusable components
6. What can be reused
7. What should be redesigned
8. Proposed Vela information architecture
9. Proposed design system
10. Proposed component hierarchy
11. Implementation plan

Then wait for approval before making the large-scale redesign.

When implementation begins, work incrementally and verify that existing functionality continues to work after each major phase.
