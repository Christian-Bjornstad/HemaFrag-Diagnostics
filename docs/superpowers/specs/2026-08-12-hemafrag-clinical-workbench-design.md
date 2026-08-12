# HemaFrag Clinical Workbench Design

**Date:** 2026-08-12  
**Status:** Approved visual direction; awaiting written-spec review  
**Branch:** `codex/ui-polish`

## Goal

Polish HemaFrag into a compact, readable clinical desktop workbench with a recognizable small-window icon, clearer Ladder Editor hierarchy, a better About page, and navigation that exposes Labeling instead of the redundant ML Training page.

## Chosen Direction

The selected direction is **Clinical Workbench**: restrained navy and blue branding, light data surfaces, high contrast, compact spacing, and clear primary actions. This is an evolutionary refinement of the current app. It does not replace the workflow or restyle the app as a marketing interface.

The design applies equally to all three analysis workspaces:

- **Klonalitet / Clonality**
- **FLT3 Analysis**
- **General**

Shared screens must show the active analysis context where that context helps prevent mistakes. The visual system must not imply that HemaFrag is only a clonality application.

## Scope

### Included

- Replace the current small-size icon treatment with an adaptive HemaFrag identity that remains recognizable at 16, 20, 24, and 32 pixels.
- Add an icon-and-`HEMAFRAG` lockup to the sidebar.
- Make source launches and packaged Windows builds use the same stable application icon and Windows taskbar identity.
- Remove **ML Training** from the Clonality sidebar and application page stack.
- Keep **Labeling** in the Clonality sidebar.
- Preserve the current Clonality, FLT3, and General routes and analysis-specific settings.
- Refine the Ladder Editor layout without changing ladder-fitting behavior.
- Redesign About into a concise branded summary with readable license and third-party information.
- Harmonize spacing, focus states, card hierarchy, and contrast in the affected UI.

### Excluded

- Changes to the Rust ladder-fitting algorithm or wheel.
- Changes to patient data, controls, classifiers, labeling data, or model training behavior.
- Removal of the underlying ML training implementation or its historical tests beyond what is required to stop exposing and constructing its page in the main application.
- Changes to analysis pipelines, report content, or saved ladder-adjustment formats.
- A collapsible or responsive sidebar system; the existing desktop navigation model remains fixed and predictable.

## Application Identity

### Icon system

The icon will use a simple clinical mark: a strong blue rounded field containing a white HemaFrag `H` combined with a short electropherogram trace. The silhouette, not fine detail, must carry the identity. The current neon DNA artwork is too intricate at title-bar and taskbar sizes and will not be used as the small application icon.

A deterministic asset script will generate the required PNG, multi-resolution ICO, and ICNS files from one design definition. The generated files remain committed so packaging does not depend on running the generator. Visual checks will inspect the 16, 20, 24, 32, 48, 128, and 256 pixel outputs.

### Runtime identity

One resource helper will resolve icon assets for source, wheel, and frozen-bundle layouts. It will prefer `app_icon.ico` on Windows, `app_icon.icns` on macOS, and `app_icon.png` on Linux, with safe fallbacks. Invalid or missing icons will produce a warning but will not block startup.

On Windows, `no.ous.hemafrag` will be set as the AppUserModelID before `QApplication` is constructed. Both `QApplication` and `MainWindow` will receive the same validated `QIcon`.

### Sidebar lockup

The existing text-only `HEMAFRAG` header will become a compact lockup with the new icon, the `HEMAFRAG` wordmark, and a subtle `Diagnostics` descriptor. The lockup must fit the current desktop sidebar without forcing the analysis names or sub-navigation to truncate.

## Navigation and Analysis Workspaces

The navigation will remain analysis-first and will visibly retain all three groups. The intended labels are:

- **Klonalitet:** Run, Ladder, Archive Runner, Log, Labeling, Settings
- **FLT3 Analysis:** Run, Ladder, Archive Runner, Log, Settings
- **General:** Run, Ladder, Log, Settings

The Clonality ML Training widget will no longer be imported, constructed, added to the stacked widget, or mapped from the sidebar. Its module may remain in the repository for historical and internal reuse.

Shortcut routing will use semantic labels rather than fixed positions so removing one Clonality page cannot shift Log, Labeling, or Settings. Alt+1, Alt+2, and Alt+3 will continue to activate Clonality, FLT3, and General respectively. Existing analysis switching and persisted settings remain unchanged.

## Ladder Editor

The Ladder Editor remains one shared tool for Clonality, FLT3, and General. Fit calculation, candidate selection, manual assignments, saved adjustments, review notes, and keyboard commands remain behaviorally unchanged.

The layout will be refined as follows:

1. Keep the file and assay metadata in a compact summary row, including the active analysis context.
2. Give the trace the largest uninterrupted area.
3. Group trace controls into **View** and **Assign** clusters so zoom/Y controls do not compete with peak-editing controls.
4. Keep Matches and Candidates in the existing right-hand editor rail.
5. Keep QC visible inside the vertical splitter, but remove height assumptions that clip the `SIZING QC` header or residual plot at a 1200×800 window.
6. Keep the action bar anchored at the bottom. Make `Save Adjustment` the only primary action; secondary and destructive actions receive quieter or warning treatments.
7. Preserve review-only controls such as `Save Note Only` when a review bundle is active.

The editor must remain usable at 1200×800 and 1024×700. At those sizes, all action buttons must remain reachable and the user must be able to reveal all QC content without horizontal scrolling. The 35 bp ladder peak receives no special reporting or visual treatment.

## About Page

About will use a compact branded header containing the icon, application name, version, and the existing clinical workflow description. A summary card will clearly separate:

- version and application identity;
- local-maintenance context;
- repository licensing status.

Third-party software, the repository notice, and the upstream MIT license will remain available in full. Their long text will move into one compact three-tab legal-information card rather than three permanently expanded tall cards.

Every `QTextBrowser` on the page will receive an explicit light background, dark foreground, readable link color, border, selection colors, and inner spacing. This removes the current system-theme-dependent dark-on-dark rendering.

## Shared Visual System

The implementation will extend the existing palette rather than introduce a second theme:

- primary blue: `#2563EB`
- sidebar navy: `#0B1724`
- page text: `#0F172A`
- body text: `#102235`
- muted text: `#64748B`
- page background: `#EEF4F8`
- card background: `#FFFFFF`
- success: `#16A34A`
- warning: `#D97706`
- danger: `#DC2626`

Controls must have visible keyboard focus. Button hierarchy must distinguish primary, secondary, and destructive actions without relying on color alone. No new animation framework or UI dependency will be added.

## Error Handling

- Missing or invalid identity assets log a warning and fall back to Qt's default window behavior.
- Missing license files continue to render an explicit `Missing file: ...` message inside the About page.
- Layout changes do not intercept or transform ladder data; existing editor exceptions and save validation remain authoritative.
- Removing ML Training from navigation must not delete model artifacts, settings, or training code.

## Verification

Automated tests will cover:

- platform-specific icon resolution and invalid-icon fallback;
- Windows AppUserModelID behavior without calling Windows APIs on other platforms;
- Clonality navigation includes Labeling and excludes ML Training;
- Clonality, FLT3, and General retain their expected labels and page routing;
- semantic keyboard shortcuts still reach Log, Labeling, and Settings after ML Training removal;
- About contains the brand/version and all required legal sections;
- About text browsers use the dedicated readable style hook;
- Ladder Editor contains the View/Assign control groups, persistent action bar, and reachable QC section at compact geometry.

Manual verification will launch the real PyQt application and inspect:

- title-bar/taskbar icon visibility at small sizes;
- sidebar lockup and all three analysis groups;
- Ladder Editor at 1200×800 and 1024×700 with a representative file;
- About contrast and legal-content expansion;
- keyboard focus and navigation;
- packaged icon selection through the canonical `build_qt.py` contract.

## Acceptance Criteria

The work is complete when:

1. The HemaFrag icon is clearly visible in the Windows title bar and taskbar at small sizes.
2. The sidebar shows the HemaFrag icon/title and retains Clonality, FLT3, and General.
3. ML Training is absent from the running app; Labeling remains accessible.
4. Existing non-ML-training routes continue to open the correct pages for each analysis.
5. Ladder Editor controls, QC, and save actions are reachable at both target window sizes without changing fitting results.
6. About has no dark-on-dark text and presents all required legal information cleanly.
7. Focused automated tests and the broader relevant test suite pass.
8. No Rust source or wheel is changed because this is a UI-only project.
