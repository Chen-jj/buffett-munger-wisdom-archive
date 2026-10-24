"""Pure verification of the public plan against the same frozen layout rules."""

from archive_core.interfaces import SubtitlePlanDTO, SubtitleRenderPlanDTO

from .layout import build_render_plan
from .models import FontMeasurer, GraphemeSegmenter, LayoutError


def validate_render_plan(
    plan: SubtitleRenderPlanDTO, source_plan: SubtitlePlanDTO,
    measurer: FontMeasurer, segmenter: GraphemeSegmenter,
) -> None:
    """Recompute measurements, offsets and deterministic choices; never trust saved QA."""
    if not isinstance(plan, SubtitleRenderPlanDTO):
        raise ValueError("plan must be a SubtitleRenderPlanDTO")
    expected = build_render_plan(
        asset_id=plan.asset_id, inputs=plan.inputs, input_media=plan.input_media,
        source_plan=source_plan, profile=plan.profile, font=plan.font, tools=plan.tools,
        measurer=measurer, segmenter=segmenter,
    )
    if expected != plan:
        raise LayoutError("Saved render plan does not match deterministic visual layout and measurement.")
