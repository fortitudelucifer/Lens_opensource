# Electron Build Placeholder

This document reserves the packaging plan for the Lens v1.1 desktop shell. The current Beta release remains a Git clone + local backend + Vite frontend workflow; Electron packaging is not part of the v1.0.0-beta release gate.

## Current Scope

- Keep a minimal `electron/` directory in the repository so future desktop packaging has a stable location.
- Keep Electron build outputs excluded by `.gitignore`, including `electron/dist/` and `electron/out/`.
- Do not bundle private chat logs, local secrets, model weights, generated analysis outputs, or runtime caches into a desktop artifact.
- Treat Electron packaging as an independent v1.1 task after Beta feedback confirms that environment setup is a major blocker.

## Placeholder Files

- `electron/main.js`: opens the existing frontend dev server from `LENS_FRONTEND_URL` or `http://127.0.0.1:5173`.
- `electron/preload.js`: exposes a minimal non-sensitive shell marker to the renderer.
- `electron/package.json`: reserves the Electron shell package metadata and scripts.

## Required Work Before Real Packaging

1. Decide whether the desktop shell only wraps the frontend or also manages the Python backend lifecycle.
2. Choose the backend packaging strategy: user-managed Conda, PyInstaller binary, Nuitka binary, or another explicit runtime bundle.
3. Define where local workspace data lives outside the app bundle, including configs, logs, generated outputs, and user-selected raw imports.
4. Add a secure first-run setup flow for backend URL, local secrets path, and workspace path.
5. Add platform-specific build scripts for Windows, macOS, and Linux only after the runtime boundary is finalized.
6. Add packaging CI checks that verify no private data, API keys, model weights, or generated artifacts are included.
7. Re-run Phase F regression plus a real desktop smoke test before publishing any installer.

## Recommended Updates For v1.1

- Replace the dev-server-only `loadURL` path with a production build path once `frontend/dist/` packaging is defined.
- Add backend health polling and a visible connection state in the desktop shell.
- Add crash logging that writes only non-sensitive diagnostics.
- Add signed installer documentation after the target platforms are confirmed.
- Add a release checklist for artifact naming, checksum generation, and privacy sweep validation.
