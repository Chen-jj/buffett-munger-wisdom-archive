"""Pure libass font selection diagnostic fixture."""
def selection(identity, index=-1):
    return (f"[Parsed_ass_0 @ 0x123] fontselect: ({identity.spec.family}, 400, 0) -> "
            f"{identity.spec.path}, {index}, {identity.postscript_name}")
