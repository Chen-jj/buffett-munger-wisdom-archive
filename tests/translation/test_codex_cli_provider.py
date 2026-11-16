"""Provider timeout configuration is checked before all external boundaries."""

import pytest
from translation.domain import PermanentProviderError
from translation.infrastructure import CodexCliChatGPTTranslationProvider


@pytest.mark.parametrize("timeout", [True, 0, -1, float("inf"), "1800", float("nan")])
def test_invalid_timeout_fails_configuration_before_preflight(timeout):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid configuration called an external boundary")
    with pytest.raises(PermanentProviderError) as caught:
        CodexCliChatGPTTranslationProvider(timeout_seconds=timeout, process_runner=forbidden,
            executable_resolver=forbidden)
    assert caught.value.code == "configuration"
