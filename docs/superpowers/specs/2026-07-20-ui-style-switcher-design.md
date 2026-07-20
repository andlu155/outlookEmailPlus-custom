# UI Style Switcher Design

## Goal

Keep the original warm Chinese-style interface as the default while retaining the new dark dashboard design as a selectable interface style. Ensure Docker Compose pulls images built from this repository's GHCR namespace.

## Design

- The existing stylesheet remains the classic UI baseline.
- The dark dashboard override is enabled only when `<html>` has `data-ui-style="dashboard"`.
- The sidebar gains an interface-style control with `经典国风` and `深色数据台` options.
- `ol_ui_style` stores the selected interface style. Missing or invalid values resolve to `classic`.
- The existing `ol_theme` light/dark toggle remains independent from the interface-style selection.
- `docker-compose.yml` uses `ghcr.io/andlu155/outlook-email-plus:${IMAGE_TAG:-latest}`.

## Validation

- A static frontend contract test checks the style selector, storage key, default value, and dashboard CSS scoping.
- A Compose configuration check verifies the image namespace.
- Existing browser-extension tests continue to pass.
