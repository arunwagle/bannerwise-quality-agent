# Bannerwise Quality Agent — UI Requirements

## Design Philosophy

**Minimalistic, functional, badge-driven.** The UI surfaces the confidence gate decision clearly with visual state differentiation (green = certified, amber = analytical) and full provenance at a glance.

---

## Layout Structure

```
┌─────────────────────────────────────────────────────────────┐
│  HEADER                                                     │
│  [Logo] Bannerwise Quality Agent    [User] [Settings] [⚙]  │
├────────────────┬────────────────────────────────────────────┤
│  LEFT NAV      │  RIGHT CONTENT AREA                        │
│                │                                            │
│  • Ask         │  (Dynamic — changes based on nav)          │
│  • History     │                                            │
│  • Corpus      │                                            │
│  • Admin       │                                            │
│                │                                            │
│                │                                            │
│                │                                            │
│                │                                            │
└────────────────┴────────────────────────────────────────────┘
```

---

## Header

| Element | Description |
| --- | --- |
| Logo + Title | "Bannerwise Quality Agent" — left aligned |
| User Avatar | Current workspace user identity (from Databricks auth) |
| Settings Icon | App configuration (threshold, Genie Space ID) |
| Status Indicator | Green dot = healthy, Red = endpoint down |

---

## Left Navigation Menu

Collapsible sidebar (default expanded, \~220px wide). Icons + labels.

| Nav Item | Icon | Description |
| --- | --- | --- |
| **Ask** | 💬 | Primary prompt input — main interaction surface |
| **History** | 🕐 | Past queries with badge, confidence, timestamp |
| **Corpus** | 📋 | Browse certified Q&A entries (read-only for non-admins) |
| **Admin** | ⚙️ | Corpus management, threshold config (admin only) |

---

## Right Content Area — Pages

### Page: Ask (Default View)

The primary interaction surface. Single prompt input with response rendering.

#### Prompt Section
- Large text input (multi-line, placeholder: *"Ask a question about your data..."*)
- Submit button (right-aligned)
- Optional: example prompts as clickable chips below input

#### Response Section (appears after submit)

Renders differently based on the gate decision:

##### State 1 — Certified Lane (Green)

```
┌─────────────────────────────────────────────────────────┐
│  ✅ HUMAN APPROVED                         Confidence: 92% │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  [Answer rendered from SME template]                    │
│                                                         │
│  ┌─── Result Table/Value ───────────────────────────┐   │
│  │  (SQL execution result formatted per template)   │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  PROVENANCE                                             │
│  • Corpus ID: QA-0047                                   │
│  • Certified by: jane.doe@company.com                   │
│  • Next review: 2025-09-01                              │
│  • SQL: SELECT ... (expandable)                         │
│  • Confidence: 0.92 (raw: 94, calibrated: 92)          │
│  • Latency: 1.2s                                       │
└─────────────────────────────────────────────────────────┘
```

- **Badge**: Green banner — "HUMAN APPROVED"
- **Confidence meter**: Circular or bar indicator showing calibrated score
- **Answer**: Rendered from the stored answer template with live data
- **Provenance drawer**: Expandable section showing full audit trail

##### State 2 — Analytical Lane (Amber)

```
┌─────────────────────────────────────────────────────────┐
│  ⚠️ NOT YET APPROVED                      Confidence: 61% │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  [Genie-generated answer]                               │
│                                                         │
│  ┌─── Generated SQL ────────────────────────────────┐   │
│  │  (Genie Conversation API output — syntax highlighted)│
│  └──────────────────────────────────────────────────┘   │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  ⚠️ This answer was generated dynamically and has not   │
│     been certified by an SME.                           │
│                                                         │
│  [🔍 Request SME Review]  [👎 Flag Incorrect]           │
├─────────────────────────────────────────────────────────┤
│  PROVENANCE                                             │
│  • Source: Genie Space (conversation API)               │
│  • Confidence: 0.61 (below 0.85 threshold)             │
│  • Reason: No certified match found                     │
│  • Latency: 3.4s                                       │
└─────────────────────────────────────────────────────────┘
```

- **Badge**: Amber banner — "NOT YET APPROVED"
- **Warning**: Clear disclaimer that answer is unverified
- **Action buttons**: "Request SME Review" triggers certification flywheel
- **Generated SQL**: Shown for transparency (collapsible)

---

### Page: History

| Column | Description |
| --- | --- |
| Timestamp | When the query was submitted |
| Question | User's original prompt (truncated) |
| Badge | 🟢 HUMAN APPROVED / 🟡 NOT YET APPROVED |
| Confidence | Calibrated score |
| Lane | Certified / Analytical |

- Click any row → expands full response + provenance
- Filter by: badge type, date range, confidence range
- Sort by: timestamp (default desc), confidence

---

### Page: Corpus

Read-only browse of the certified Q&A corpus (Delta table).

| Column | Description |
| --- | --- |
| ID | Corpus entry identifier |
| Question | Certified question text |
| Status | `certified` / `draft` / `expired` |
| Next Review | Date — red highlight if past due |
| Certified By | SME who approved |
| Last Updated | Timestamp |

- Search bar for filtering by question text
- Status badge pills (green = certified, gray = draft, red = expired)
- Click row → shows full detail (SQL template, answer template, parameters)

---

### Page: Admin (Restricted)

Only visible to users in the `ADMIN_USERS` list.

#### Sections:

1. **Threshold Configuration**
   - Confidence threshold slider (0.50 – 1.00, default 0.85)
   - Save button with confirmation

2. **Corpus Management**
   - Add new Q&A entry form
   - Edit existing entries (question, SQL, answer template)
   - Certify / Revoke certification
   - Bulk import from CSV

3. **System Status**
   - Vector Search index health
   - Serving endpoint status
   - MLflow tracing link
   - Recent error log

---

## Visual Design Tokens

| Token | Value |
| --- | --- |
| Primary color | `#1b3a4b` (dark navy — header, nav) |
| Certified green | `#2e7d32` (badge, border for State 1) |
| Analytical amber | `#f57c00` (badge, border for State 2) |
| Background | `#f5f5f5` (light gray) |
| Card background | `#ffffff` |
| Font | System font stack (Inter / -apple-system / Segoe UI) |
| Border radius | `8px` (cards), `4px` (buttons) |
| Nav width | `220px` (expanded), `60px` (collapsed) |

---

## Flow Mapping to UI States

```
User Prompt (Ask page)
       │
       ▼
┌──────────────────────┐
│ TIER 3: Confidence   │    ← Invisible to user (backend)
│ Gate processing      │
└──────────────────────┘
       │
       ├── confidence >= 0.85 AND certified
       │         │
       │         ▼
       │   ┌─────────────────────┐
       │   │ STATE 1 UI          │
       │   │ Green badge          │
       │   │ Template answer      │
       │   │ Full provenance      │
       │   └─────────────────────┘
       │
       └── confidence < 0.85
                 │
                 ▼
           ┌─────────────────────┐
           │ STATE 2 UI          │
           │ Amber badge          │
           │ Genie answer         │
           │ "Request SME Review" │
           └─────────────────────┘
```

---

## Supporting Tiers (Backend — Not Directly in UI)

| Tier | Role | UI Visibility |
| --- | --- | --- |
| TIER 1 — Governed Semantic Layer | UC tables + Metric Views, SQL Warehouse, Genie Space | Indirect (powers both lanes) |
| TIER 2 — Certified Q&A Corpus | Delta table + Vector Search Delta Sync index | Corpus page (read-only browse) |
| TIER 3 — Deterministic Confidence Gate | embed → retrieve → rerank → calibrate → gate | Confidence score in response |
| TIER 5 — Governance | MLflow tracing, staleness demotion | Admin page (system status) |

---

## Certification Flywheel (Triggered from UI)

1. User clicks **"Request SME Review"** on a State 2 response
2. System logs the question + Genie-generated SQL + context
3. SME reviews in Admin page → certifies (adds to corpus) or rejects
4. Approved Q&A grows the corpus → Vector Search index auto-syncs
5. Next identical question hits the Certified Lane

---

## Responsive Behavior

- **Desktop** (>1024px): Full layout with expanded nav
- **Tablet** (768–1024px): Collapsed nav (icons only), full content area
- **Mobile** (<768px): Nav as hamburger menu overlay, single-column content
