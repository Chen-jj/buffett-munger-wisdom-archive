from orchestration.domain.models import MediaSelection, PipelineCommand, STAGES


def build_pipeline_handler(*, runtime=None):
    from orchestration.infrastructure.composition import build_pipeline_handler as build
    return build(runtime=runtime)
