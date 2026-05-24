# subtitle_rendering AGENTS.md

## Module Purpose

`subtitle_rendering` owns subtitle styling, ASS generation, burn-in planning, ffmpeg execution, and render artifact metadata.

## Responsibilities

- Convert validated subtitle documents into styled ASS or render-ready assets.
- Plan ffmpeg commands for hard-subtitle outputs without hiding user-impacting quality settings.
- Capture render settings, input hashes, output path, and review sidecars.
- Keep visual style decisions separate from SRT text processing.

## Layering Rules

- `domain/`: render profile, subtitle style, render input set, render plan, and render artifact concepts.
- `application/`: build-ass, render-video, verify-render-inputs, and generate-render-manifest use cases.
- `infrastructure/`: `pysubs2` ASS adapter, ffmpeg process runner, font discovery, and filesystem outputs.
- `interfaces/`: CLI handlers, render progress messages, and review/orchestration-facing summaries.

## Technology Direction

- Use `ffmpeg`/libass for burn-in rendering behind an adapter.
- Treat quality settings such as CRF, preset, resolution, and subtitle style as explicit profiles.
- Prefer dry-run command planning for debugging and review.

## Phased Goals

- Phase 1: Separate ASS/style generation from ffmpeg execution.
- Phase 2: Add render manifest and input validation before expensive jobs.
- Phase 3: Support multiple render profiles such as sample, review, and final.
